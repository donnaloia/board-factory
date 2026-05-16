"""OpenAI Sora-backed I2V provider — *true* image-to-video.

Unlike :mod:`openai` (which produces a still and crossfades it), this
provider calls the actual Sora 2 video API and decodes the resulting
MP4 into PIL frames the rest of the pipeline already understands.

Per-job shape:

  1. **Vision pass** (``gpt-4o`` via :mod:`_motion_director`) turns the
     user's animation prompt into N distinct, image-grounded motion
     plans. Each candidate gets its own plan so the gallery shows three
     meaningfully different takes on the same direction.
  2. **Pad** the source PNG onto a Sora-compatible canvas (1280×720 or
     720×1280 — picked to match the cell's aspect). Sora requires the
     ``input_reference`` to match the target ``size`` exactly and emits
     RGB video, so transparency is dropped at this boundary.
  3. **Submit & poll** ``POST /v1/videos`` once per candidate with the
     plan as the prompt; poll ``GET /v1/videos/{id}`` until
     ``completed`` (or fail fast on ``failed``). Sora is asynchronous
     and a single 4-second 720p render typically takes 1–3 minutes; a
     3-candidate job is therefore minutes-long, not seconds-long.
  4. **Download + decode** the MP4 with ``ffmpeg``, then **crop** back
     to the source's centred region and **resize** to the cell's
     native size.
  5. **Resample** Sora's frames to the target ``fps × duration_ms`` the
     rest of the pipeline expects (``steps.loop_close`` then closes the
     loop, ``steps.encode`` rasterises to GIF / APNG).

Cost: at the time of writing, OpenAI bills Sora 2 at $0.10 per second
and Sora 2 Pro at $0.30 per second (720p). One 4-second clip is the
minimum; the per-job total is therefore meaningfully higher than the
gpt-image-2 path. See :meth:`SoraI2VProvider.cost_estimate`.
"""

from __future__ import annotations

import base64
import io
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from PIL import Image

from .base import Clip
from ._motion_director import (
    COST_PER_CALL_USD as _VISION_COST_USD,
    plan_motion_variants,
)


_BASE_URL = "https://api.openai.com/v1"

#: Sizes Sora 2 actually accepts. Anything else is rejected server-side.
_SORA2_SIZES_LANDSCAPE = "1280x720"
_SORA2_SIZES_PORTRAIT = "720x1280"

#: Per-second list pricing (USD). Update if OpenAI changes pricing.
#: Only used for the UI estimate / job ledger; actual billing happens
#: server-side at OpenAI.
_PRICE_PER_SECOND_USD: dict[str, float] = {
    "sora-2": 0.10,
    "sora-2-pro": 0.30,
}

#: Minimum Sora ``seconds`` per call. Spec lists 4 / 8 / 12 / 16 / 20.
_ALLOWED_SECONDS = (4, 8, 12, 16, 20)

#: How long we wait (in seconds) for a single Sora render before giving
#: up. Sora's "several minutes" guidance × a healthy safety margin so a
#: backed-up queue surfaces as an explicit timeout rather than a hung
#: job.
_RENDER_TIMEOUT_S = 900.0
_POLL_INTERVAL_S = 10.0

#: Initial sleep before the first poll. The /videos endpoint never
#: returns ``completed`` on the create call; skipping that first GET
#: round-trip cuts ~one request per job.
_INITIAL_WAIT_S = 5.0


@dataclass(frozen=True)
class SoraI2VProvider:
    """OpenAI Sora image-to-video provider.

    Frozen dataclass so the provider is hashable and trivially
    testable. ``api_key`` is required and must be the **user's** key —
    never read from environment so missing-key errors surface at the
    provider boundary rather than mid-pipeline.
    """

    api_key: str
    model: str = "sora-2"
    seconds: int = 4
    name: str = "sora"
    #: Extra debug metadata the job ledger can surface. Not part of
    #: the provider protocol — purely informational.
    extras: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def model_id(self) -> str:
        return f"{self.model}@{self.seconds}s"

    def generate(
        self,
        source_png: bytes,
        *,
        fps: int,
        duration_ms: int,
        candidates: int,
        seed: int | None = None,
        animation_prompt: str = "",
    ) -> list[Clip]:
        if not (self.api_key or "").strip():
            raise RuntimeError(
                "Sora I2V provider requires the user's OpenAI API key. "
                "Save it in Account → Connections → OpenAI / ChatGPT, "
                "or switch SPACE_ANIMATIONS_PROVIDER=mock in the env."
            )
        if candidates <= 0:
            return []
        if self.seconds not in _ALLOWED_SECONDS:
            raise RuntimeError(
                f"Sora `seconds` must be one of {_ALLOWED_SECONDS}; "
                f"got {self.seconds}. Override with SPACE_ANIMATIONS_SORA_SECONDS."
            )
        if not (animation_prompt or "").strip():
            raise RuntimeError(
                "Sora I2V provider requires a non-empty animation_prompt; "
                "the web layer enforces this at the route boundary."
            )

        source = Image.open(io.BytesIO(source_png)).convert("RGBA")
        target_size = _pick_target_size(source.size)
        padded_png, crop_box = _pad_to_target(source, target_size)

        plans = plan_motion_variants(
            source_png=source_png,
            animation_prompt=animation_prompt,
            n=candidates,
            api_key=self.api_key,
        )

        clips: list[Clip] = []
        for i in range(candidates):
            plan = plans[i] if i < len(plans) else animation_prompt
            prompt = _compose_sora_prompt(animation_prompt, plan)
            video_id = self._create_video_job(
                prompt=prompt,
                size=target_size,
                seconds=self.seconds,
                input_reference_png=padded_png,
            )
            self._wait_for_completion(video_id)
            mp4_bytes = self._download_mp4(video_id)
            raw_frames = _decode_mp4_to_frames(mp4_bytes)
            cropped = [_crop_and_resize(f, crop_box, source.size) for f in raw_frames]
            frames = _resample_frames(
                cropped,
                source_seconds=float(self.seconds),
                target_fps=fps,
                target_duration_ms=duration_ms,
            )
            short_plan = (plan or "").strip().replace("\n", " ")[:80]
            clips.append(
                Clip(
                    frames=frames,
                    fps=fps,
                    seed=seed,
                    notes=f"sora · {short_plan} ({self.model}, {self.seconds}s)",
                )
            )
        return clips

    def cost_estimate(self, *, candidates: int, duration_ms: int) -> float:
        # Sora billing depends on size + seconds × candidates. The vision
        # pass costs the same fixed amount as the gpt-image-2 path
        # because we still use the director to differentiate candidates.
        per_sec = _PRICE_PER_SECOND_USD.get(self.model, 0.10)
        return _VISION_COST_USD + candidates * self.seconds * per_sec

    # ────────────────────────── HTTP helpers ─────────────────────

    def _create_video_job(
        self,
        *,
        prompt: str,
        size: str,
        seconds: int,
        input_reference_png: bytes,
    ) -> str:
        """``POST /v1/videos`` — returns the video job id.

        Sora accepts ``input_reference`` as a JSON object pointing at
        either a ``file_id`` or an ``image_url``. We base64-encode the
        padded PNG inline so the entire request is JSON.
        """
        data_url = (
            "data:image/png;base64,"
            + base64.b64encode(input_reference_png).decode("ascii")
        )
        body = {
            "model": self.model,
            "prompt": prompt,
            "size": size,
            "seconds": str(seconds),
            "input_reference": {"image_url": data_url},
        }
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                f"{_BASE_URL}/videos",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        if not r.is_success:
            raise RuntimeError(
                f"Sora /videos create failed ({r.status_code}): {_error_body(r)}"
            )
        try:
            video_id = r.json()["id"]
        except Exception as exc:
            raise RuntimeError(
                f"Sora /videos create returned an unrecognised body: {r.text[:200]}"
            ) from exc
        return str(video_id)

    def _wait_for_completion(self, video_id: str) -> None:
        """Poll ``GET /v1/videos/{id}`` until ``completed`` — or raise."""
        deadline = time.monotonic() + _RENDER_TIMEOUT_S
        time.sleep(_INITIAL_WAIT_S)
        while time.monotonic() < deadline:
            status, error = self._fetch_status(video_id)
            if status == "completed":
                return
            if status == "failed":
                raise RuntimeError(
                    f"Sora job {video_id} failed: {error or 'no error message provided'}"
                )
            time.sleep(_POLL_INTERVAL_S)
        raise RuntimeError(
            f"Sora job {video_id} did not complete within "
            f"{int(_RENDER_TIMEOUT_S)}s — try again later or switch to "
            "SPACE_ANIMATIONS_PROVIDER=openai for the faster (lower-fidelity) path."
        )

    def _fetch_status(self, video_id: str) -> tuple[str, str | None]:
        with httpx.Client(timeout=60.0) as client:
            r = client.get(
                f"{_BASE_URL}/videos/{video_id}",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        if not r.is_success:
            # A transient 5xx during polling is recoverable on the next
            # tick; surface anything else immediately.
            if r.status_code >= 500:
                return ("in_progress", None)
            raise RuntimeError(
                f"Sora /videos/{video_id} GET failed ({r.status_code}): {_error_body(r)}"
            )
        body = r.json()
        status = str(body.get("status") or "")
        err = body.get("error")
        err_msg = err.get("message") if isinstance(err, dict) else None
        return (status, err_msg)

    def _download_mp4(self, video_id: str) -> bytes:
        with httpx.Client(timeout=300.0, follow_redirects=True) as client:
            r = client.get(
                f"{_BASE_URL}/videos/{video_id}/content",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        if not r.is_success:
            raise RuntimeError(
                f"Sora /videos/{video_id}/content GET failed ({r.status_code}): "
                f"{_error_body(r)}"
            )
        return r.content


# ────────────────────────── prompt composition ─────────────────────────


def _compose_sora_prompt(animation_prompt: str, plan: str) -> str:
    """Wrap a per-candidate plan in Sora-flavoured framing.

    Sora prompts respond well to shot-type / motion / lighting
    language, but we should NOT invent direction the user did not ask
    for — the plan already grounds the motion in the source image.
    """
    user = (animation_prompt or "").strip()
    plan_text = (plan or "").strip() or user
    parts = [
        "Animate the supplied reference image.",
        "Preserve composition, palette, and silhouette of every element "
        "not explicitly moving.",
    ]
    if user:
        parts.append(f"User direction: {user}")
    parts.append(f"Motion: {plan_text}")
    return " ".join(parts)


# ────────────────────────── padding / cropping ─────────────────────────


def _pick_target_size(source_size: tuple[int, int]) -> str:
    """Pick a Sora-compatible canvas that best matches the cell aspect."""
    w, h = source_size
    if w >= h:
        return _SORA2_SIZES_LANDSCAPE
    return _SORA2_SIZES_PORTRAIT


def _pad_to_target(
    source: Image.Image, target_size_str: str
) -> tuple[bytes, tuple[int, int, int, int]]:
    """Centre-pad ``source`` onto a black canvas of ``target_size``.

    Returns ``(png_bytes, crop_box)`` where ``crop_box`` is the
    ``(x0, y0, x1, y1)`` rectangle inside the target canvas that
    actually contains the cell — used after generation to crop the
    Sora video back to the cell's region.
    """
    tw, th = _parse_size(target_size_str)
    sw, sh = source.size
    scale = min(tw / sw, th / sh)
    nw = max(1, int(round(sw * scale)))
    nh = max(1, int(round(sh * scale)))
    resized = source.convert("RGBA").resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (tw, th), (0, 0, 0))
    ox = (tw - nw) // 2
    oy = (th - nh) // 2
    canvas.paste(resized, (ox, oy), resized)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue(), (ox, oy, ox + nw, oy + nh)


def _crop_and_resize(
    frame: Image.Image,
    crop_box: tuple[int, int, int, int],
    out_size: tuple[int, int],
) -> Image.Image:
    """Crop the cell region out of a Sora frame and resize it back to native."""
    cropped = frame.crop(crop_box).convert("RGBA")
    if cropped.size != out_size:
        cropped = cropped.resize(out_size, Image.LANCZOS)
    return cropped


def _parse_size(size_str: str) -> tuple[int, int]:
    w, h = size_str.lower().split("x", 1)
    return int(w), int(h)


# ────────────────────────── frame resampling ─────────────────────────


def _resample_frames(
    source_frames: list[Image.Image],
    *,
    source_seconds: float,
    target_fps: int,
    target_duration_ms: int,
) -> list[Image.Image]:
    """Pick frames out of ``source_frames`` for the target fps + duration.

    For each output frame ``i`` we sample the source frame whose
    timestamp is closest to ``i / target_fps``. If the target window is
    longer than what Sora produced we cap at the source length (the
    loop-closer downstream will still close it).
    """
    if not source_frames:
        raise RuntimeError("Sora returned a video with zero decodable frames.")
    if target_fps <= 0 or target_duration_ms <= 0:
        return list(source_frames)
    n_src = len(source_frames)
    source_fps = n_src / max(source_seconds, 0.001)
    target_count = max(2, int(round(target_fps * target_duration_ms / 1000.0)))
    out: list[Image.Image] = []
    for i in range(target_count):
        t = i / target_fps
        src_idx = int(round(t * source_fps))
        if src_idx >= n_src:
            src_idx = n_src - 1
        out.append(source_frames[src_idx])
    return out


# ────────────────────────── MP4 decode ─────────────────────────


def _decode_mp4_to_frames(mp4_bytes: bytes) -> list[Image.Image]:
    """Decode an MP4 byte string to a list of PIL ``RGBA`` frames.

    Uses ``ffmpeg`` via subprocess so we add no extra Python deps.
    Frames are written to a temp dir and loaded one by one. We raise a
    clear error if ``ffmpeg`` is missing from the container — see the
    Dockerfile (``apt-get install ffmpeg``).
    """
    if not mp4_bytes:
        raise RuntimeError("Sora returned an empty MP4 body.")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg is required to decode Sora video output but was not found "
            "on PATH. Rebuild the board-factory image (`make rebuild`)."
        )
    with tempfile.TemporaryDirectory(prefix="sora-decode-") as tmp:
        tmp_path = Path(tmp)
        mp4_path = tmp_path / "in.mp4"
        mp4_path.write_bytes(mp4_bytes)
        out_pattern = tmp_path / "frame_%05d.png"
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(mp4_path),
                "-f",
                "image2",
                str(out_pattern),
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed to decode Sora MP4 (exit {proc.returncode}): "
                f"{proc.stderr.strip()[:240]}"
            )
        frame_paths = sorted(tmp_path.glob("frame_*.png"))
        if not frame_paths:
            raise RuntimeError(
                "ffmpeg succeeded but produced no frames — the MP4 may be malformed."
            )
        # Load eagerly so the temp dir can be cleaned up immediately.
        return [Image.open(p).convert("RGBA").copy() for p in frame_paths]


# ────────────────────────── misc ─────────────────────────


def _error_body(r: httpx.Response) -> str:
    try:
        return r.json().get("error", {}).get("message", "") or r.text[:200]
    except Exception:
        return r.text[:200]
