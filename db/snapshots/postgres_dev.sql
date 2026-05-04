--
-- PostgreSQL database dump
--

\restrict WqFa4aZV8HUU96WFpa0bfJJektEGdEeT6ebNmQzL0nDUTCmqV5CaxkllibcrObH

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

ALTER TABLE IF EXISTS ONLY public.user_secrets DROP CONSTRAINT IF EXISTS user_secrets_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.owned_boards DROP CONSTRAINT IF EXISTS owned_boards_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.owned_boards DROP CONSTRAINT IF EXISTS owned_boards_board_uuid_fkey;
ALTER TABLE IF EXISTS ONLY public.browser_sessions DROP CONSTRAINT IF EXISTS browser_sessions_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.asset_versions DROP CONSTRAINT IF EXISTS asset_versions_board_uuid_fkey;
DROP INDEX IF EXISTS public.ix_users_email;
DROP INDEX IF EXISTS public.ix_user_secrets_user_kind;
DROP INDEX IF EXISTS public.ix_user_secrets_user_id;
DROP INDEX IF EXISTS public.ix_owned_boards_user_id;
DROP INDEX IF EXISTS public.ix_job_runs_ended_at;
DROP INDEX IF EXISTS public.ix_cost_entries_ts;
DROP INDEX IF EXISTS public.ix_browser_sessions_user_id;
DROP INDEX IF EXISTS public.ix_asset_versions_board_relpath;
DROP INDEX IF EXISTS public.ix_asset_versions_board_cell;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_pkey;
ALTER TABLE IF EXISTS ONLY public.user_secrets DROP CONSTRAINT IF EXISTS user_secrets_pkey;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS uq_users_username;
ALTER TABLE IF EXISTS ONLY public.owned_boards DROP CONSTRAINT IF EXISTS owned_boards_user_id_path_slug_key;
ALTER TABLE IF EXISTS ONLY public.owned_boards DROP CONSTRAINT IF EXISTS owned_boards_pkey;
ALTER TABLE IF EXISTS ONLY public.job_runs DROP CONSTRAINT IF EXISTS job_runs_pkey;
ALTER TABLE IF EXISTS ONLY public.cost_entries DROP CONSTRAINT IF EXISTS cost_entries_pkey;
ALTER TABLE IF EXISTS ONLY public.browser_sessions DROP CONSTRAINT IF EXISTS browser_sessions_pkey;
ALTER TABLE IF EXISTS ONLY public.board_games DROP CONSTRAINT IF EXISTS board_games_pkey;
ALTER TABLE IF EXISTS ONLY public.asset_versions DROP CONSTRAINT IF EXISTS asset_versions_pkey;
ALTER TABLE IF EXISTS ONLY public.alembic_version DROP CONSTRAINT IF EXISTS alembic_version_pkc;
ALTER TABLE IF EXISTS public.user_secrets ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.cost_entries ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS public.asset_versions ALTER COLUMN id DROP DEFAULT;
DROP TABLE IF EXISTS public.users;
DROP SEQUENCE IF EXISTS public.user_secrets_id_seq;
DROP TABLE IF EXISTS public.user_secrets;
DROP TABLE IF EXISTS public.owned_boards;
DROP TABLE IF EXISTS public.job_runs;
DROP SEQUENCE IF EXISTS public.cost_entries_id_seq;
DROP TABLE IF EXISTS public.cost_entries;
DROP TABLE IF EXISTS public.browser_sessions;
DROP TABLE IF EXISTS public.board_games;
DROP SEQUENCE IF EXISTS public.asset_versions_id_seq;
DROP TABLE IF EXISTS public.asset_versions;
DROP TABLE IF EXISTS public.alembic_version;
SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: asset_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.asset_versions (
    id integer NOT NULL,
    board_uuid character varying(36) NOT NULL,
    category character varying(32) NOT NULL,
    asset_id character varying(256) NOT NULL,
    basename character varying(512) NOT NULL,
    rel_path character varying(512) NOT NULL,
    sha256 character varying(64),
    ts_ms bigint NOT NULL,
    meta_json text
);


--
-- Name: asset_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.asset_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: asset_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.asset_versions_id_seq OWNED BY public.asset_versions.id;


--
-- Name: board_games; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.board_games (
    id character varying(36) NOT NULL,
    body_json text NOT NULL,
    updated_ms bigint NOT NULL,
    palette_json text,
    palette_gpl_text text,
    style_lock_updated_ms bigint
);


--
-- Name: browser_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.browser_sessions (
    sid character varying(64) NOT NULL,
    user_id character varying(64) NOT NULL,
    created_ms bigint NOT NULL,
    last_seen_ms bigint NOT NULL
);


--
-- Name: cost_entries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cost_entries (
    id integer NOT NULL,
    ts double precision NOT NULL,
    op character varying(128) NOT NULL,
    target character varying(256),
    units integer NOT NULL,
    usd double precision NOT NULL
);


--
-- Name: cost_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.cost_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: cost_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.cost_entries_id_seq OWNED BY public.cost_entries.id;


--
-- Name: job_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_runs (
    id character varying(24) NOT NULL,
    label character varying(512) NOT NULL,
    operation character varying(128) NOT NULL,
    target character varying(256),
    status character varying(32) NOT NULL,
    progress double precision NOT NULL,
    eta_s double precision,
    cost_estimate double precision NOT NULL,
    cost_actual double precision NOT NULL,
    started_at double precision,
    ended_at double precision,
    error text,
    log_json text NOT NULL
);


--
-- Name: owned_boards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.owned_boards (
    board_uuid character varying(36) NOT NULL,
    user_id character varying(64) NOT NULL,
    path_slug character varying(128) NOT NULL,
    created_ms bigint NOT NULL,
    list_order integer DEFAULT 0 NOT NULL
);


--
-- Name: user_secrets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_secrets (
    id integer NOT NULL,
    user_id character varying(64) NOT NULL,
    kind character varying(64) NOT NULL,
    ciphertext text NOT NULL
);


--
-- Name: user_secrets_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_secrets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_secrets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_secrets_id_seq OWNED BY public.user_secrets.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id character varying(64) NOT NULL,
    email character varying(320) NOT NULL,
    password_hash character varying(128) NOT NULL,
    display_name character varying(120) NOT NULL,
    icon_glyph character varying(8) NOT NULL,
    icon_color character varying(16) NOT NULL,
    created_ms bigint NOT NULL,
    last_login_ms bigint NOT NULL,
    username character varying(64) NOT NULL
);


--
-- Name: asset_versions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_versions ALTER COLUMN id SET DEFAULT nextval('public.asset_versions_id_seq'::regclass);


--
-- Name: cost_entries id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_entries ALTER COLUMN id SET DEFAULT nextval('public.cost_entries_id_seq'::regclass);


--
-- Name: user_secrets id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_secrets ALTER COLUMN id SET DEFAULT nextval('public.user_secrets_id_seq'::regclass);


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.alembic_version (version_num) FROM stdin;
0015_board_uuid_user_paths
\.


--
-- Data for Name: asset_versions; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.asset_versions (id, board_uuid, category, asset_id, basename, rel_path, sha256, ts_ms, meta_json) FROM stdin;
\.


--
-- Data for Name: board_games; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.board_games (id, body_json, updated_ms, palette_json, palette_gpl_text, style_lock_updated_ms) FROM stdin;
748e880d-ceab-46e3-96f8-7684903a2727	{"project":"damnation","style":{"reference_image":"mockup/board.png","palette_size":36,"prompt":""},"board_size":[1920,1080],"centerpiece":{"bbox":[700,180,1220,900],"target_size":[520,720],"prompt":"","needs_active":false,"active_kind":"none"},"board_spaces":{"layout":{"top_row":{"count":12,"start":[0,0],"spacing":160,"axis":"x","size":[160,180]},"bottom_row":{"count":12,"start":[0,900],"spacing":160,"axis":"x","size":[160,180]},"left_col":{"count":5,"start":[0,180],"spacing":144,"axis":"y","size":[180,144]},"right_col":{"count":5,"start":[1740,180],"spacing":144,"axis":"y","size":[180,144]}},"designs":[{"id":"corner_tl","prompt":"","space_kind":"standard","positions":["top_row.0"]},{"id":"corner_tr","prompt":"","space_kind":"standard","positions":["top_row.11"]},{"id":"corner_bl","prompt":"","space_kind":"standard","positions":["bottom_row.0"]},{"id":"corner_br","prompt":"","space_kind":"standard","positions":["bottom_row.11"]},{"id":"top_banner_a","prompt":"","space_kind":"standard","positions":["top_row.5"]},{"id":"top_banner_b","prompt":"","space_kind":"standard","positions":["top_row.7"]},{"id":"top_space_a","prompt":"","space_kind":"standard","positions":["top_row.1","top_row.4","top_row.8"]},{"id":"top_space_b","prompt":"","space_kind":"standard","positions":["top_row.2","top_row.6","top_row.9"]},{"id":"top_space_c","prompt":"","space_kind":"standard","positions":["top_row.3","top_row.10"]},{"id":"bottom_banner_a","prompt":"","space_kind":"standard","positions":["bottom_row.5"]},{"id":"bottom_banner_b","prompt":"","space_kind":"standard","positions":["bottom_row.6"]},{"id":"bottom_space_a","prompt":"","space_kind":"standard","positions":["bottom_row.1","bottom_row.4"]},{"id":"bottom_space_b","prompt":"","space_kind":"standard","positions":["bottom_row.2","bottom_row.10"]},{"id":"bottom_space_c","prompt":"","space_kind":"standard","positions":["bottom_row.3","bottom_row.8"]},{"id":"bottom_space_d","prompt":"","space_kind":"standard","positions":["bottom_row.9"]},{"id":"bottom_battle","prompt":"","space_kind":"standard","positions":["bottom_row.7"]},{"id":"side_property","prompt":"","space_kind":"standard","positions":["left_col.0","left_col.1","left_col.3","left_col.4","right_col.1","right_col.2","right_col.3"]},{"id":"side_battle","prompt":"","space_kind":"standard","positions":["left_col.2","right_col.0","right_col.4"]},{"id":"top_battle","prompt":"","space_kind":"standard","positions":["top_row.3"]}]},"feature_panels":{"panels":[{"id":"panel_left_top","bbox":[180,180,440,420],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_left_mid","bbox":[180,420,440,660],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_left_bot","bbox":[180,660,440,900],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_top","bbox":[440,180,700,420],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_mid","bbox":[440,420,700,660],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_bot","bbox":[440,660,700,900],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_cright_top","bbox":[1220,180,1480,420],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_cright_mid","bbox":[1220,420,1480,660],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_cright_bot","bbox":[1220,660,1480,900],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_right_top","bbox":[1480,180,1740,420],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_right_mid","bbox":[1480,420,1740,660],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"},{"id":"panel_right_bot","bbox":[1480,660,1740,900],"target_size":[260,240],"prompt":"","needs_active":false,"active_kind":"none"}]},"frame":{"enabled":false,"apply_to_panels":true,"apply_to_spaces":false},"generation":{"palette_size":36,"provider":"openai","openai":{"model":"gpt-image-1","quality":"medium"},"pixellab":{"model":"pixflux_sharp"},"configured":true}}	1777785247950	\N	\N	\N
ed1456f7-12ef-48d3-ac59-4c93634c8a33	{"project": "fantasy-quest", "board_size": [1920, 1080], "style": {"reference_image": "mockup/board.png", "palette_size": 36, "prompt": ""}, "centerpiece": {"bbox": [700, 180, 1220, 900], "target_size": [520, 720], "prompt": "", "needs_active": false, "active_kind": "none"}, "board_spaces": {"layout": {"top_row": {"count": 12, "start": [0, 0], "spacing": 160, "axis": "x", "size": [160, 180]}, "bottom_row": {"count": 12, "start": [0, 900], "spacing": 160, "axis": "x", "size": [160, 180]}, "left_col": {"count": 5, "start": [0, 180], "spacing": 144, "axis": "y", "size": [180, 144]}, "right_col": {"count": 5, "start": [1740, 180], "spacing": 144, "axis": "y", "size": [180, 144]}}, "designs": [{"id": "corner_tl", "prompt": "", "space_kind": "standard", "positions": ["top_row.0"]}, {"id": "corner_tr", "prompt": "", "space_kind": "standard", "positions": ["top_row.11"]}, {"id": "corner_bl", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.0"]}, {"id": "corner_br", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.11"]}, {"id": "top_banner_a", "prompt": "", "space_kind": "standard", "positions": ["top_row.5"]}, {"id": "top_banner_b", "prompt": "", "space_kind": "standard", "positions": ["top_row.7"]}, {"id": "top_space_a", "prompt": "", "space_kind": "standard", "positions": ["top_row.1", "top_row.4", "top_row.8"]}, {"id": "top_space_b", "prompt": "", "space_kind": "standard", "positions": ["top_row.2", "top_row.6", "top_row.9"]}, {"id": "top_space_c", "prompt": "", "space_kind": "standard", "positions": ["top_row.3", "top_row.10"]}, {"id": "bottom_banner_a", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.5"]}, {"id": "bottom_banner_b", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.6"]}, {"id": "bottom_space_a", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.1", "bottom_row.4"]}, {"id": "bottom_space_b", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.2", "bottom_row.10"]}, {"id": "bottom_space_c", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.3", "bottom_row.8"]}, {"id": "bottom_space_d", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.9"]}, {"id": "bottom_battle", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.7"]}, {"id": "side_property", "prompt": "", "space_kind": "standard", "positions": ["left_col.0", "left_col.1", "left_col.3", "left_col.4", "right_col.1", "right_col.2", "right_col.3"]}, {"id": "side_battle", "prompt": "", "space_kind": "standard", "positions": ["left_col.2", "right_col.0", "right_col.4"]}, {"id": "top_battle", "prompt": "", "space_kind": "standard", "positions": ["top_row.3"]}]}, "feature_panels": {"panels": [{"id": "panel_left_top", "bbox": [180, 180, 440, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_left_mid", "bbox": [180, 420, 440, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_left_bot", "bbox": [180, 660, 440, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cleft_top", "bbox": [440, 180, 700, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cleft_mid", "bbox": [440, 420, 700, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cleft_bot", "bbox": [440, 660, 700, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cright_top", "bbox": [1220, 180, 1480, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cright_mid", "bbox": [1220, 420, 1480, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cright_bot", "bbox": [1220, 660, 1480, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_right_top", "bbox": [1480, 180, 1740, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_right_mid", "bbox": [1480, 420, 1740, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_right_bot", "bbox": [1480, 660, 1740, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}]}, "frame": {"enabled": false, "apply_to_panels": true, "apply_to_spaces": false}, "generation": {"palette_size": 36, "provider": "openai", "openai": {"model": "gpt-image-2", "quality": "low"}, "pixellab": {"model": "pixflux_sharp"}, "configured": false}}	1777687089499	\N	\N	\N
3de2757b-bbe2-4f74-9e36-d2e7d3285b48	{"project": "revelation x 2", "board_size": [1920, 1080], "style": {"reference_image": "mockup/board.png", "palette_size": 36, "prompt": ""}, "centerpiece": {"bbox": [700, 180, 1220, 900], "target_size": [520, 720], "prompt": "", "needs_active": false, "active_kind": "none"}, "board_spaces": {"layout": {"top_row": {"count": 12, "start": [0, 0], "spacing": 160, "axis": "x", "size": [160, 180]}, "bottom_row": {"count": 12, "start": [0, 900], "spacing": 160, "axis": "x", "size": [160, 180]}, "left_col": {"count": 5, "start": [0, 180], "spacing": 144, "axis": "y", "size": [180, 144]}, "right_col": {"count": 5, "start": [1740, 180], "spacing": 144, "axis": "y", "size": [180, 144]}}, "designs": [{"id": "corner_tl", "prompt": "", "space_kind": "standard", "positions": ["top_row.0"]}, {"id": "corner_tr", "prompt": "", "space_kind": "standard", "positions": ["top_row.11"]}, {"id": "corner_bl", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.0"]}, {"id": "corner_br", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.11"]}, {"id": "top_banner_a", "prompt": "", "space_kind": "standard", "positions": ["top_row.5"]}, {"id": "top_banner_b", "prompt": "", "space_kind": "standard", "positions": ["top_row.7"]}, {"id": "top_space_a", "prompt": "", "space_kind": "standard", "positions": ["top_row.1", "top_row.4", "top_row.8"]}, {"id": "top_space_b", "prompt": "", "space_kind": "standard", "positions": ["top_row.2", "top_row.6", "top_row.9"]}, {"id": "top_space_c", "prompt": "", "space_kind": "standard", "positions": ["top_row.3", "top_row.10"]}, {"id": "bottom_banner_a", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.5"]}, {"id": "bottom_banner_b", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.6"]}, {"id": "bottom_space_a", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.1", "bottom_row.4"]}, {"id": "bottom_space_b", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.2", "bottom_row.10"]}, {"id": "bottom_space_c", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.3", "bottom_row.8"]}, {"id": "bottom_space_d", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.9"]}, {"id": "bottom_battle", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.7"]}, {"id": "side_property", "prompt": "", "space_kind": "standard", "positions": ["left_col.0", "left_col.1", "left_col.3", "left_col.4", "right_col.1", "right_col.2", "right_col.3"]}, {"id": "side_battle", "prompt": "", "space_kind": "standard", "positions": ["left_col.2", "right_col.0", "right_col.4"]}, {"id": "top_battle", "prompt": "", "space_kind": "standard", "positions": ["top_row.3"]}]}, "feature_panels": {"panels": [{"id": "panel_left_top", "bbox": [180, 180, 440, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_left_mid", "bbox": [180, 420, 440, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_left_bot", "bbox": [180, 660, 440, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cleft_top", "bbox": [440, 180, 700, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cleft_mid", "bbox": [440, 420, 700, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cleft_bot", "bbox": [440, 660, 700, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cright_top", "bbox": [1220, 180, 1480, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cright_mid", "bbox": [1220, 420, 1480, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cright_bot", "bbox": [1220, 660, 1480, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_right_top", "bbox": [1480, 180, 1740, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_right_mid", "bbox": [1480, 420, 1740, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_right_bot", "bbox": [1480, 660, 1740, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}]}, "frame": {"enabled": false, "apply_to_panels": true, "apply_to_spaces": false}, "generation": {"palette_size": 36, "provider": "openai", "openai": {"model": "gpt-image-2", "quality": "medium"}, "pixellab": {"model": "pixflux_sharp"}, "configured": true}}	1777699202856	\N	\N	\N
e92c3dc7-ec23-4f36-9f78-ee04abf6106b	{"project": "revelation x 1", "board_size": [1920, 1080], "style": {"reference_image": "mockup/board.png", "palette_size": 24, "prompt": ""}, "centerpiece": {"bbox": [700, 180, 1220, 900], "target_size": [520, 720], "prompt": "", "needs_active": false, "active_kind": "none"}, "board_spaces": {"layout": {"top_row": {"count": 12, "start": [0, 0], "spacing": 160, "axis": "x", "size": [160, 180]}, "bottom_row": {"count": 12, "start": [0, 900], "spacing": 160, "axis": "x", "size": [160, 180]}, "left_col": {"count": 5, "start": [0, 180], "spacing": 144, "axis": "y", "size": [180, 144]}, "right_col": {"count": 5, "start": [1740, 180], "spacing": 144, "axis": "y", "size": [180, 144]}}, "designs": [{"id": "corner_tl", "prompt": "", "space_kind": "standard", "positions": ["top_row.0"]}, {"id": "corner_tr", "prompt": "", "space_kind": "standard", "positions": ["top_row.11"]}, {"id": "corner_bl", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.0"]}, {"id": "corner_br", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.11"]}, {"id": "top_banner_a", "prompt": "", "space_kind": "standard", "positions": ["top_row.5"]}, {"id": "top_banner_b", "prompt": "", "space_kind": "standard", "positions": ["top_row.7"]}, {"id": "top_space_a", "prompt": "", "space_kind": "standard", "positions": ["top_row.1", "top_row.4", "top_row.8"]}, {"id": "top_space_b", "prompt": "", "space_kind": "standard", "positions": ["top_row.2", "top_row.6", "top_row.9"]}, {"id": "top_space_c", "prompt": "", "space_kind": "standard", "positions": ["top_row.3", "top_row.10"]}, {"id": "bottom_banner_a", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.5"]}, {"id": "bottom_banner_b", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.6"]}, {"id": "bottom_space_a", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.1", "bottom_row.4"]}, {"id": "bottom_space_b", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.2", "bottom_row.10"]}, {"id": "bottom_space_c", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.3", "bottom_row.8"]}, {"id": "bottom_space_d", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.9"]}, {"id": "bottom_battle", "prompt": "", "space_kind": "standard", "positions": ["bottom_row.7"]}, {"id": "side_property", "prompt": "", "space_kind": "standard", "positions": ["left_col.0", "left_col.1", "left_col.3", "left_col.4", "right_col.1", "right_col.2", "right_col.3"]}, {"id": "side_battle", "prompt": "", "space_kind": "standard", "positions": ["left_col.2", "right_col.0", "right_col.4"]}, {"id": "top_battle", "prompt": "", "space_kind": "standard", "positions": ["top_row.3"]}]}, "feature_panels": {"panels": [{"id": "panel_left_top", "bbox": [180, 180, 440, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_left_mid", "bbox": [180, 420, 440, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_left_bot", "bbox": [180, 660, 440, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cleft_top", "bbox": [440, 180, 700, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cleft_mid", "bbox": [440, 420, 700, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cleft_bot", "bbox": [440, 660, 700, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cright_top", "bbox": [1220, 180, 1480, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cright_mid", "bbox": [1220, 420, 1480, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_cright_bot", "bbox": [1220, 660, 1480, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_right_top", "bbox": [1480, 180, 1740, 420], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_right_mid", "bbox": [1480, 420, 1740, 660], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}, {"id": "panel_right_bot", "bbox": [1480, 660, 1740, 900], "target_size": [260, 240], "prompt": "", "needs_active": false, "active_kind": "none"}]}, "frame": {"enabled": false, "apply_to_panels": true, "apply_to_spaces": false}, "generation": {"palette_size": 24, "provider": "openai", "openai": {"model": "gpt-image-1", "quality": "low"}, "pixellab": {"model": "pixflux_sharp"}, "configured": true}}	1777699222186	\N	\N	\N
02ad5018-b82e-49ce-ad23-43d20ff06c9d	{"project":"pink desert","style":{"reference_image":"mockup/board.png","palette_size":24,"prompt":"The board evokes an ancient desert city with rich history, using a warm, earthy palette. Accents of pink, gold, and turquoise create a mystical and adventurous mood, complemented by pixel-art style with detailed textures."},"board_size":[1920,1080],"centerpiece":{"bbox":[700,180,1220,900],"target_size":[520,720],"prompt":"Majestic palace by a river, surrounded by mountains.","needs_active":false,"active_kind":"none"},"board_spaces":{"layout":{"top_row":{"count":12,"start":[0,0],"spacing":160,"axis":"x","size":[160,180]},"bottom_row":{"count":12,"start":[0,900],"spacing":160,"axis":"x","size":[160,180]},"left_col":{"count":5,"start":[0,180],"spacing":144,"axis":"y","size":[180,144]},"right_col":{"count":5,"start":[1740,180],"spacing":144,"axis":"y","size":[180,144]}},"designs":[{"id":"corner_tl","prompt":"Grand castle with palm trees, sunset backdrop.","space_kind":"standard","positions":["top_row.0"]},{"id":"corner_tr","prompt":"Regal peacock perched elegantly, vibrant feathers.","space_kind":"standard","positions":["top_row.11"]},{"id":"corner_bl","prompt":"Oasis with camels, serene desert sunset.","space_kind":"standard","positions":["bottom_row.0"]},{"id":"corner_br","prompt":"Ancient stone obelisk under the moonlight.","space_kind":"standard","positions":["bottom_row.11"]},{"id":"top_banner_a","prompt":"Golden hourglass, shimmering sand inside.","space_kind":"standard","positions":["top_row.5"]},{"id":"top_banner_b","prompt":"Mystical lamp with intricate designs.","space_kind":"standard","positions":["top_row.7"]},{"id":"top_space_a","prompt":"Tiled fountain with crystal-clear water.","space_kind":"standard","positions":["top_row.1","top_row.4","top_row.8"]},{"id":"top_space_b","prompt":"Cluster of pink crystals, enchanted glow.","space_kind":"standard","positions":["top_row.2","top_row.6","top_row.9"]},{"id":"top_space_c","prompt":"Camel caravan traversing endless sand dunes.","space_kind":"standard","positions":["top_row.3","top_row.10"]},{"id":"bottom_banner_a","prompt":"Embroidered tapestry with desert motifs.","space_kind":"standard","positions":["bottom_row.5"]},{"id":"bottom_banner_b","prompt":"Golden coins stack, gleaming under the sun.","space_kind":"standard","positions":["bottom_row.6"]},{"id":"bottom_space_a","prompt":"Rolling dunes dotted with solitary cacti.","space_kind":"standard","positions":["bottom_row.1","bottom_row.4"]},{"id":"bottom_space_b","prompt":"Scorpion poised under the scorching sun.","space_kind":"standard","positions":["bottom_row.2","bottom_row.10"]},{"id":"bottom_space_c","prompt":"Nomadic tent, vibrant fabrics, spices wafting.","space_kind":"standard","positions":["bottom_row.3","bottom_row.8"]},{"id":"bottom_space_d","prompt":"Desert city skyline silhouetted at twilight.","space_kind":"standard","positions":["bottom_row.9"]},{"id":"bottom_battle","prompt":"Ancient warrior in armor, ready for battle.","space_kind":"standard","positions":["bottom_row.7"]},{"id":"side_property","prompt":"Sand-swept pathways winding past aged ruins.","space_kind":"standard","positions":["left_col.0","left_col.1","left_col.3","left_col.4","right_col.1","right_col.2","right_col.3"]},{"id":"side_battle","prompt":"Epic sword duel, dynamic and intense.","space_kind":"standard","positions":["left_col.2","right_col.0","right_col.4"]},{"id":"top_battle","prompt":"Warrior atop a rearing horse, defiant stance.","space_kind":"standard","positions":["top_row.3"]}]},"feature_panels":{"panels":[{"id":"panel_left_top","bbox":[180,180,440,420],"target_size":[260,240],"prompt":"Cactus cluster in arid landscape.","needs_active":false,"active_kind":"none"},{"id":"panel_left_mid","bbox":[180,420,440,660],"target_size":[260,240],"prompt":"Scorpion surrounded by desert flora.","needs_active":false,"active_kind":"none"},{"id":"panel_left_bot","bbox":[180,660,440,900],"target_size":[260,240],"prompt":"Glimpse of ancient city through palms.","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_top","bbox":[440,180,700,420],"target_size":[260,240],"prompt":"Starry night over crescent dunes.","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_mid","bbox":[440,420,700,660],"target_size":[260,240],"prompt":"Desert horizon with radiant sunrise.","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_bot","bbox":[440,660,700,900],"target_size":[260,240],"prompt":"Lone traveler shaded by a rock.","needs_active":false,"active_kind":"none"},{"id":"panel_cright_top","bbox":[1220,180,1480,420],"target_size":[260,240],"prompt":"Arabian stallion galloping, mane flowing.","needs_active":false,"active_kind":"none"},{"id":"panel_cright_mid","bbox":[1220,420,1480,660],"target_size":[260,240],"prompt":"Parched desert with a distant mirage.","needs_active":false,"active_kind":"none"},{"id":"panel_cright_bot","bbox":[1220,660,1480,900],"target_size":[260,240],"prompt":"Mystic runes glowing on ancient stone.","needs_active":false,"active_kind":"none"},{"id":"panel_right_top","bbox":[1480,180,1740,420],"target_size":[260,240],"prompt":"Silhouette of camels, distant dunes.","needs_active":false,"active_kind":"none"},{"id":"panel_right_mid","bbox":[1480,420,1740,660],"target_size":[260,240],"prompt":"Ornate lantern casting intricate shadows.","needs_active":false,"active_kind":"none"},{"id":"panel_right_bot","bbox":[1480,660,1740,900],"target_size":[260,240],"prompt":"Crescent moon illuminating desert sands.","needs_active":false,"active_kind":"none"}]},"frame":{"enabled":true,"apply_to_panels":true,"apply_to_spaces":false},"generation":{"palette_size":24,"provider":"openai","openai":{"model":"gpt-image-1","quality":"low"},"pixellab":{"model":"pixflux_sharp"},"configured":true}}	1777785226992	[[243, 197, 167], [241, 189, 159], [239, 185, 154], [241, 181, 151], [234, 179, 150], [235, 178, 141], [224, 178, 157], [237, 169, 153], [225, 170, 155], [230, 167, 138], [217, 165, 149], [231, 154, 147], [221, 156, 145], [222, 153, 127], [227, 141, 133], [217, 140, 125], [213, 145, 124], [211, 138, 117], [211, 132, 115], [196, 136, 115], [207, 122, 111], [192, 119, 101], [190, 104, 100], [177, 98, 92], [172, 97, 89], [171, 90, 89], [164, 91, 83], [148, 93, 78], [157, 80, 80], [147, 78, 75], [146, 74, 75], [143, 67, 70], [128, 66, 62], [109, 63, 52], [105, 49, 48], [79, 39, 35]]	GIMP Palette\nName: BoardFactory (36 colors)\nColumns: 8\n#\n243 197 167\tRGB-f3c5a7\n241 189 159\tRGB-f1bd9f\n239 185 154\tRGB-efb99a\n241 181 151\tRGB-f1b597\n234 179 150\tRGB-eab396\n235 178 141\tRGB-ebb28d\n224 178 157\tRGB-e0b29d\n237 169 153\tRGB-eda999\n225 170 155\tRGB-e1aa9b\n230 167 138\tRGB-e6a78a\n217 165 149\tRGB-d9a595\n231 154 147\tRGB-e79a93\n221 156 145\tRGB-dd9c91\n222 153 127\tRGB-de997f\n227 141 133\tRGB-e38d85\n217 140 125\tRGB-d98c7d\n213 145 124\tRGB-d5917c\n211 138 117\tRGB-d38a75\n211 132 115\tRGB-d38473\n196 136 115\tRGB-c48873\n207 122 111\tRGB-cf7a6f\n192 119 101\tRGB-c07765\n190 104 100\tRGB-be6864\n177  98  92\tRGB-b1625c\n172  97  89\tRGB-ac6159\n171  90  89\tRGB-ab5a59\n164  91  83\tRGB-a45b53\n148  93  78\tRGB-945d4e\n157  80  80\tRGB-9d5050\n147  78  75\tRGB-934e4b\n146  74  75\tRGB-924a4b\n143  67  70\tRGB-8f4346\n128  66  62\tRGB-80423e\n109  63  52\tRGB-6d3f34\n105  49  48\tRGB-693130\n 79  39  35\tRGB-4f2723\n	1777687802475
2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	{"project":"I Luv Cake","style":{"reference_image":"mockup/board.png","palette_size":36,"prompt":"Whimsical, candyland theme with pastel colors. Accents include pink, mint green, lavender, and chocolate brown. The mood is playful and sweet, reminiscent of a fantasy confectionery world."},"board_size":[1920,1080],"centerpiece":{"bbox":[700,180,1220,900],"target_size":[520,720],"prompt":"Giant tiered cake in candyland landscape","needs_active":false,"active_kind":"none"},"board_spaces":{"layout":{"top_row":{"count":12,"start":[0,0],"spacing":160,"axis":"x","size":[160,180]},"bottom_row":{"count":12,"start":[0,900],"spacing":160,"axis":"x","size":[160,180]},"left_col":{"count":5,"start":[0,180],"spacing":144,"axis":"y","size":[180,144]},"right_col":{"count":5,"start":[1740,180],"spacing":144,"axis":"y","size":[180,144]}},"designs":[{"id":"corner_tl","prompt":"Cupcake with pink frosting and cherry","space_kind":"standard","positions":["top_row.0"]},{"id":"corner_tr","prompt":"Chocolate truffle with golden wrapper","space_kind":"standard","positions":["top_row.11"]},{"id":"corner_bl","prompt":"Slice of fruit-topped cheesecake","space_kind":"event","positions":["bottom_row.0"]},{"id":"corner_br","prompt":"Caramel apple with candy sprinkles","space_kind":"standard","positions":["bottom_row.11"]},{"id":"top_banner_a","prompt":"Mint green macaron illustration","space_kind":"standard","positions":["top_row.5"]},{"id":"top_banner_b","prompt":"Stack of colorful donuts","space_kind":"standard","positions":["top_row.7"]},{"id":"top_space_a","prompt":"Slice of swiss roll cake","space_kind":"standard","positions":["top_row.1","top_row.4","top_row.8"]},{"id":"top_space_b","prompt":"Blueberry tart on a plate","space_kind":"standard","positions":["top_row.2","top_row.6","top_row.9"]},{"id":"top_space_c","prompt":"Glazed donut with sprinkles","space_kind":"standard","positions":["top_row.3","top_row.10"]},{"id":"bottom_banner_a","prompt":"Assorted cookies in a basket","space_kind":"standard","positions":["bottom_row.5"]},{"id":"bottom_banner_b","prompt":"Plate of assorted chocolates","space_kind":"standard","positions":["bottom_row.6"]},{"id":"bottom_space_a","prompt":"Chocolate eclair with cream","space_kind":"standard","positions":["bottom_row.1","bottom_row.4"]},{"id":"bottom_space_b","prompt":"Vanilla cupcake with sprinkles","space_kind":"standard","positions":["bottom_row.2","bottom_row.10"]},{"id":"bottom_space_c","prompt":"Slice of strawberry cake","space_kind":"standard","positions":["bottom_row.3","bottom_row.8"]},{"id":"bottom_space_d","prompt":"Tall glass of milkshake","space_kind":"event","positions":["bottom_row.9"]},{"id":"bottom_battle","prompt":"Tower of pancakes with syrup","space_kind":"standard","positions":["bottom_row.7"]},{"id":"side_property","prompt":"Macaron tower with icing","space_kind":"standard","positions":["left_col.0","left_col.1","left_col.3","left_col.4","right_col.1","right_col.2","right_col.3"]},{"id":"side_battle","prompt":"Chocolate lava cake with spoon","space_kind":"standard","positions":["left_col.2","right_col.0","right_col.4"]},{"id":"top_battle","prompt":"Plate of colorful cupcakes","space_kind":"standard","positions":["top_row.3"]}]},"feature_panels":{"panels":[{"id":"panel_left_top","bbox":[180,180,440,420],"target_size":[260,240],"prompt":"Set of pastel-colored cake icons","needs_active":false,"active_kind":"none"},{"id":"panel_left_mid","bbox":[180,420,440,660],"target_size":[260,240],"prompt":"Five lavender cupcake silhouettes","needs_active":false,"active_kind":"none"},{"id":"panel_left_bot","bbox":[180,660,440,900],"target_size":[260,240],"prompt":"Pink heart shapes on a stripe","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_top","bbox":[440,180,700,420],"target_size":[260,240],"prompt":"Green star symbols in a row","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_mid","bbox":[440,420,700,660],"target_size":[260,240],"prompt":"Three round pastry icons","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_bot","bbox":[440,660,700,900],"target_size":[260,240],"prompt":"Cakes on stands; purple background","needs_active":false,"active_kind":"none"},{"id":"panel_cright_top","bbox":[1220,180,1480,420],"target_size":[260,240],"prompt":"Series of outlined cake shapes","needs_active":false,"active_kind":"none"},{"id":"panel_cright_mid","bbox":[1220,420,1480,660],"target_size":[260,240],"prompt":"Desserts with a berry topping","needs_active":false,"active_kind":"none"},{"id":"panel_cright_bot","bbox":[1220,660,1480,900],"target_size":[260,240],"prompt":"Transparent jar with candy swirls","needs_active":false,"active_kind":"none"},{"id":"panel_right_top","bbox":[1480,180,1740,420],"target_size":[260,240],"prompt":"Trio of decorated cupcakes","needs_active":false,"active_kind":"none"},{"id":"panel_right_mid","bbox":[1480,420,1740,660],"target_size":[260,240],"prompt":"Four circular treat emblems","needs_active":false,"active_kind":"none"},{"id":"panel_right_bot","bbox":[1480,660,1740,900],"target_size":[260,240],"prompt":"Row of fruit-topped pastries","needs_active":false,"active_kind":"none"}]},"frame":{"enabled":false,"apply_to_panels":true,"apply_to_spaces":false},"generation":{"palette_size":36,"provider":"openai","openai":{"model":"gpt-image-2","quality":"medium"},"pixellab":{"model":"pixflux_sharp"},"configured":true}}	1777865442975	[[237, 208, 165], [219, 197, 149], [217, 193, 150], [238, 187, 136], [238, 187, 117], [199, 187, 138], [236, 177, 140], [234, 176, 112], [215, 175, 140], [171, 176, 144], [232, 161, 136], [230, 148, 128], [226, 159, 97], [223, 144, 88], [200, 148, 122], [196, 138, 142], [196, 143, 82], [191, 137, 81], [163, 149, 119], [221, 131, 89], [190, 134, 84], [186, 133, 88], [204, 120, 69], [199, 101, 59], [177, 127, 85], [175, 103, 63], [161, 103, 62], [132, 103, 68], [163, 75, 34], [131, 71, 30], [142, 53, 22], [115, 49, 17], [93, 50, 22], [80, 37, 11], [75, 34, 10], [67, 24, 5]]	GIMP Palette\nName: BoardFactory (36 colors)\nColumns: 8\n#\n237 208 165\tRGB-edd0a5\n219 197 149\tRGB-dbc595\n217 193 150\tRGB-d9c196\n238 187 136\tRGB-eebb88\n238 187 117\tRGB-eebb75\n199 187 138\tRGB-c7bb8a\n236 177 140\tRGB-ecb18c\n234 176 112\tRGB-eab070\n215 175 140\tRGB-d7af8c\n171 176 144\tRGB-abb090\n232 161 136\tRGB-e8a188\n230 148 128\tRGB-e69480\n226 159  97\tRGB-e29f61\n223 144  88\tRGB-df9058\n200 148 122\tRGB-c8947a\n196 138 142\tRGB-c48a8e\n196 143  82\tRGB-c48f52\n191 137  81\tRGB-bf8951\n163 149 119\tRGB-a39577\n221 131  89\tRGB-dd8359\n190 134  84\tRGB-be8654\n186 133  88\tRGB-ba8558\n204 120  69\tRGB-cc7845\n199 101  59\tRGB-c7653b\n177 127  85\tRGB-b17f55\n175 103  63\tRGB-af673f\n161 103  62\tRGB-a1673e\n132 103  68\tRGB-846744\n163  75  34\tRGB-a34b22\n131  71  30\tRGB-83471e\n142  53  22\tRGB-8e3516\n115  49  17\tRGB-733111\n 93  50  22\tRGB-5d3216\n 80  37  11\tRGB-50250b\n 75  34  10\tRGB-4b220a\n 67  24   5\tRGB-431805\n	1777822181122
ef5082cd-a41e-4319-9b9d-1f42842a518c	{"project":"rando board","style":{"reference_image":"mockup/board.png","palette_size":24,"prompt":"Fantasy-themed pixel art with intricate details. Bright, luminescent crystal blues, rich forest greens, golden sunlit tones, and deep amethyst purples create a magical and adventurous mood."},"board_size":[1920,1080],"centerpiece":{"bbox":[700,180,1220,900],"target_size":[520,720],"prompt":"Majestic crystal spire amidst enchanted landscape.","needs_active":false,"active_kind":"none"},"board_spaces":{"layout":{"top_row":{"count":12,"start":[0,0],"spacing":160,"axis":"x","size":[160,180]},"bottom_row":{"count":12,"start":[0,900],"spacing":160,"axis":"x","size":[160,180]},"left_col":{"count":5,"start":[0,180],"spacing":144,"axis":"y","size":[180,144]},"right_col":{"count":5,"start":[1740,180],"spacing":144,"axis":"y","size":[180,144]}},"designs":[{"id":"corner_tl","prompt":"Golden compass with intricate details.","space_kind":"standard","positions":["top_row.0"]},{"id":"corner_tr","prompt":"Ancient stone tower on cliff.","space_kind":"standard","positions":["top_row.11"]},{"id":"corner_bl","prompt":"Cloudy mountain path with snow.","space_kind":"standard","positions":["bottom_row.0"]},{"id":"corner_br","prompt":"Mystical green vortex swirling.","space_kind":"standard","positions":["bottom_row.11"]},{"id":"top_banner_a","prompt":"Shield with crossed swords emblem.","space_kind":"standard","positions":["top_row.5"]},{"id":"top_banner_b","prompt":"Golden crown on velvet pillow.","space_kind":"standard","positions":["top_row.7"]},{"id":"top_space_a","prompt":"Rustic wooden bridge over stream.","space_kind":"standard","positions":["top_row.1","top_row.4","top_row.8"]},{"id":"top_space_b","prompt":"Sunny meadow with colorful flowers.","space_kind":"standard","positions":["top_row.2","top_row.6","top_row.9"]},{"id":"top_space_c","prompt":"Quaint village market scene.","space_kind":"standard","positions":["top_row.3","top_row.10"]},{"id":"bottom_banner_a","prompt":"Heated blacksmith forge glowing.","space_kind":"standard","positions":["bottom_row.5"]},{"id":"bottom_banner_b","prompt":"Ornate treasure chest with gems.","space_kind":"standard","positions":["bottom_row.6"]},{"id":"bottom_space_a","prompt":"Winding forest path lined with trees.","space_kind":"standard","positions":["bottom_row.1","bottom_row.4"]},{"id":"bottom_space_b","prompt":"Lush field with windmill spinning.","space_kind":"standard","positions":["bottom_row.2","bottom_row.10"]},{"id":"bottom_space_c","prompt":"Path leading into an ancient cave.","space_kind":"standard","positions":["bottom_row.3","bottom_row.8"]},{"id":"bottom_space_d","prompt":"Knight's training ground with armor.","space_kind":"standard","positions":["bottom_row.9"]},{"id":"bottom_battle","prompt":"Circular arena with wooden spikes.","space_kind":"standard","positions":["bottom_row.7"]},{"id":"side_property","prompt":"Serene countryside path with fence.","space_kind":"standard","positions":["left_col.0","left_col.1","left_col.3","left_col.4","right_col.1","right_col.2","right_col.3"]},{"id":"side_battle","prompt":"War-torn battlefield with smoke.","space_kind":"standard","positions":["left_col.2","right_col.0","right_col.4"]},{"id":"top_battle","prompt":"Path through vibrant purple cave.","space_kind":"standard","positions":["top_row.3"]}]},"feature_panels":{"panels":[{"id":"panel_left_top","bbox":[180,180,440,420],"target_size":[260,240],"prompt":"Misty enchanted forest with fairies.","needs_active":false,"active_kind":"none"},{"id":"panel_left_mid","bbox":[180,420,440,660],"target_size":[260,240],"prompt":"Stone path through ancient ruins.","needs_active":false,"active_kind":"none"},{"id":"panel_left_bot","bbox":[180,660,440,900],"target_size":[260,240],"prompt":"Desert canyon with towering cliffs.","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_top","bbox":[440,180,700,420],"target_size":[260,240],"prompt":"Fertile valley with crystal river.","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_mid","bbox":[440,420,700,660],"target_size":[260,240],"prompt":"Sunset over golden wheat fields.","needs_active":false,"active_kind":"none"},{"id":"panel_cleft_bot","bbox":[440,660,700,900],"target_size":[260,240],"prompt":"Mountain stone path with waterfall.","needs_active":false,"active_kind":"none"},{"id":"panel_cright_top","bbox":[1220,180,1480,420],"target_size":[260,240],"prompt":"Twilight forest with glowing mushrooms.","needs_active":false,"active_kind":"none"},{"id":"panel_cright_mid","bbox":[1220,420,1480,660],"target_size":[260,240],"prompt":"Charming village under full moon.","needs_active":false,"active_kind":"none"},{"id":"panel_cright_bot","bbox":[1220,660,1480,900],"target_size":[260,240],"prompt":"Lava river flanked by molten rocks.","needs_active":false,"active_kind":"none"},{"id":"panel_right_top","bbox":[1480,180,1740,420],"target_size":[260,240],"prompt":"Frozen tundra with glacial crevasse.","needs_active":false,"active_kind":"none"},{"id":"panel_right_mid","bbox":[1480,420,1740,660],"target_size":[260,240],"prompt":"Whispering woods with hidden paths.","needs_active":false,"active_kind":"none"},{"id":"panel_right_bot","bbox":[1480,660,1740,900],"target_size":[260,240],"prompt":"Lush meadow with grazing unicorns.","needs_active":false,"active_kind":"none"}]},"frame":{"enabled":false,"apply_to_panels":true,"apply_to_spaces":false},"generation":{"palette_size":24,"provider":"openai","openai":{"model":"gpt-image-1","quality":"medium"},"pixellab":{"model":"pixflux_sharp"},"configured":true}}	1777869553753	[[218, 213, 169], [208, 185, 118], [194, 157, 84], [128, 175, 164], [119, 145, 114], [159, 119, 60], [124, 114, 58], [92, 112, 73], [55, 111, 122], [120, 81, 44], [95, 71, 36], [74, 82, 44], [77, 58, 30], [42, 78, 88], [48, 74, 31], [38, 57, 55], [38, 57, 22], [79, 40, 27], [63, 35, 22], [54, 40, 26], [53, 20, 21], [39, 42, 37], [40, 37, 14], [39, 17, 20], [22, 42, 39], [22, 42, 18], [22, 29, 21], [24, 13, 16], [11, 36, 45], [8, 30, 39], [13, 31, 23], [8, 24, 29], [10, 22, 19], [6, 17, 19], [8, 14, 11], [4, 6, 5]]	GIMP Palette\nName: BoardFactory (36 colors)\nColumns: 8\n#\n218 213 169\tRGB-dad5a9\n208 185 118\tRGB-d0b976\n194 157  84\tRGB-c29d54\n128 175 164\tRGB-80afa4\n119 145 114\tRGB-779172\n159 119  60\tRGB-9f773c\n124 114  58\tRGB-7c723a\n 92 112  73\tRGB-5c7049\n 55 111 122\tRGB-376f7a\n120  81  44\tRGB-78512c\n 95  71  36\tRGB-5f4724\n 74  82  44\tRGB-4a522c\n 77  58  30\tRGB-4d3a1e\n 42  78  88\tRGB-2a4e58\n 48  74  31\tRGB-304a1f\n 38  57  55\tRGB-263937\n 38  57  22\tRGB-263916\n 79  40  27\tRGB-4f281b\n 63  35  22\tRGB-3f2316\n 54  40  26\tRGB-36281a\n 53  20  21\tRGB-351415\n 39  42  37\tRGB-272a25\n 40  37  14\tRGB-28250e\n 39  17  20\tRGB-271114\n 22  42  39\tRGB-162a27\n 22  42  18\tRGB-162a12\n 22  29  21\tRGB-161d15\n 24  13  16\tRGB-180d10\n 11  36  45\tRGB-0b242d\n  8  30  39\tRGB-081e27\n 13  31  23\tRGB-0d1f17\n  8  24  29\tRGB-08181d\n 10  22  19\tRGB-0a1613\n  6  17  19\tRGB-061113\n  8  14  11\tRGB-080e0b\n  4   6   5\tRGB-040605\n	1777699452042
\.


--
-- Data for Name: browser_sessions; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.browser_sessions (sid, user_id, created_ms, last_seen_ms) FROM stdin;
8m1fomRi_SbjicZlBHWL4r3kj-sNk3e_	46c004b7a2a9482398aa262d103cf96e	1777682466977	1777923381036
LnZ7ZvRf5dDxciMtYz038Hn8JDxZoPLo	46c004b7a2a9482398aa262d103cf96e	1777822775286	1777870488690
\.


--
-- Data for Name: cost_entries; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.cost_entries (id, ts, op, target, units, usd) FROM stdin;
1	1777522295.587781	regen.spaces	top_space_c	1	0.033
2	1777525776.698406	generate.spaces	\N	19	0.099
3	1777525886.476444	regen.panels	panel_right_mid	1	0.066
4	1777525951.642067	generate.spaces	\N	16	0.066
5	1777529815.083902	generate.spaces	\N	14	0.231
6	1777576791.5446534	generate.spaces	\N	6	0.198
7	1777576906.5071611	regen.centerpiece	centerpiece	1	0.132
8	1777577003.6838493	regen.panels	panel_cleft_top	1	0.066
9	1777577137.8737102	regen.panels	panel_left_top	1	0.066
10	1777582892.2840974	regen.centerpiece	centerpiece	1	0.132
11	1777583809.5376704	generate.all	\N	9	0.594
12	1777584315.5400016	regen.panels	panel_cleft_top	1	0.066
13	1777594561.3796024	generate.all	\N	31	0.066
14	1777596072.09651	generate.all	\N	30	1.353
15	1777596133.2490542	regen.centerpiece	centerpiece	1	0.132
16	1777597255.1096866	regen.centerpiece	centerpiece	1	0.132
17	1777597712.5082278	regen.centerpiece	centerpiece	1	0.504
18	1777597857.988321	regen.panels	panel_cleft_bot	1	0.252
19	1777597955.3875077	regen.centerpiece	centerpiece	1	0.504
20	1777598258.8238	regen.panels	panel_cright_bot	1	0.252
21	1777598424.3110778	regen.spaces	side_property	1	0.126
22	1777693949.3700116	regen.centerpiece	centerpiece	1	0.504
23	1777694032.1702898	regen.panels	panel_cleft_bot	1	0.252
24	1777694081.058559	regen.panels	panel_right_mid	1	0.252
25	1777694132.502988	regen.spaces	bottom_space_b	1	0.033
26	1777694198.2368574	regen.panels	panel_cleft_top	1	0.066
27	1777694251.7974167	regen.panels	panel_right_bot	1	0.066
28	1777694313.4876456	regen.panels	panel_right_top	1	0.066
29	1777698184.892462	regen.panels	panel_cleft_mid	1	0.066
30	1777698237.1749644	regen.panels	panel_left_mid	1	0.066
31	1777698277.641056	regen.panels	panel_left_bot	1	0.066
32	1777698335.8562622	regen.panels	panel_cright_bot	1	0.066
33	1777698397.6110928	regen.spaces	top_space_a	1	0.033
34	1777698489.4926996	regen.centerpiece	centerpiece	1	0.132
35	1777698542.498407	regen.centerpiece	centerpiece	1	0.132
36	1777698589.1083348	regen.panels	panel_cright_top	1	0.066
37	1777698633.1273072	regen.centerpiece	centerpiece	1	0.132
38	1777698778.7916403	regen.panels	panel_cright_mid	1	0.066
39	1777698959.5581615	regen.panels	panel_left_mid	1	0.066
40	1777699551.1885905	regen.spaces	side_property	1	0.033
41	1777699585.975832	regen.centerpiece	centerpiece	1	0.132
42	1777700586.4317973	regen.centerpiece	centerpiece	1	0.132
43	1777782913.8242157	regen.spaces	top_battle	1	0.126
44	1777782968.3448136	regen.panels	panel_cright_mid	1	0.252
45	1777783030.345756	regen.centerpiece	centerpiece	1	0.504
46	1777783098.4070272	regen.panels	panel_cleft_mid	1	0.252
47	1777824277.1513875	regen.panels	panel_cleft_mid	1	0.252
48	1777824355.7633438	regen.centerpiece	centerpiece	1	0.504
49	1777824887.2380402	regen.panels	panel_cleft_mid	1	0.252
50	1777824955.8877223	regen.panels	panel_cright_mid	1	0.252
51	1777825019.5828774	regen.panels	panel_left_bot	1	0.252
52	1777825198.5252936	regen.panels	panel_cleft_top	1	0.252
53	1777825373.0213332	regen.panels	panel_cleft_top	1	0.252
54	1777825447.6417677	regen.panels	panel_cright_bot	1	0.252
55	1777825588.014294	regen.panels	panel_left_top	1	0.252
56	1777825724.0835056	regen.panels	panel_left_top	1	0.252
57	1777825789.7829027	regen.panels	panel_cleft_bot	1	0.252
58	1777825926.8438766	regen.panels	panel_cright_bot	1	0.252
59	1777826004.6098459	regen.panels	panel_left_mid	1	0.252
60	1777826080.4527583	regen.panels	panel_cright_top	1	0.252
61	1777826268.518825	regen.panels	panel_cright_top	1	0.252
62	1777826351.8379042	regen.panels	panel_right_top	1	0.252
63	1777826465.4517906	regen.spaces	bottom_space_d	1	0.126
64	1777844385.4585123	regen.panels	panel_right_mid	1	0.252
65	1777844484.5768583	regen.panels	panel_right_bot	1	0.252
66	1777844606.7330527	regen.panels	panel_right_top	1	0.252
67	1777844784.125085	regen.panels	panel_right_top	1	0.252
68	1777844857.648319	regen.panels	panel_left_bot	1	0.252
69	1777845103.8112535	regen.panels	panel_left_bot	1	0.252
70	1777845170.8689032	regen.panels	panel_right_top	1	0.252
71	1777845234.9492385	regen.panels	panel_right_bot	1	0.252
72	1777845333.92216	regen.spaces	corner_bl	1	0.126
73	1777846721.036357	regen.panels	panel_right_top	1	0.252
74	1777846878.2624776	regen.panels	panel_right_top	1	0.252
75	1777847123.288468	regen.panels	panel_cright_mid	1	0.252
76	1777847316.4987233	regen.panels	panel_cright_bot	1	0.252
77	1777847695.1257856	regen.panels	panel_cright_bot	1	0.252
78	1777847881.7679906	regen.panels	panel_cright_bot	1	0.252
79	1777864809.5372415	regen.panels	panel_cright_top	1	0.126
80	1777864856.8239894	regen.panels	panel_cleft_top	1	0.126
\.


--
-- Data for Name: job_runs; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.job_runs (id, label, operation, target, status, progress, eta_s, cost_estimate, cost_actual, started_at, ended_at, error, log_json) FROM stdin;
d760818bb9d7	Extract style from mockup	style	untitled-board-mom9qwhn	done	1	\N	0	0	1777687800.906743	1777687802.4799588	\N	["style-lock  (0/3)", "extracting 36-color palette from board.png", "  palette  (1/3)", "  swatch  (2/3)", "  style-sheet  (3/3)", "palette  -> /repo/boards/untitled-board-mom9qwhn/workspace/style/palette.json", "swatch   -> /repo/boards/untitled-board-mom9qwhn/workspace/style/palette_swatch.png", "sheet    -> /repo/boards/untitled-board-mom9qwhn/workspace/style/style_sheet.png"]
a4fdc8e9a698	Analyze mockup with GPT-4o	analyze	untitled-board-mom9qwhn	done	1	\N	0.08	0.08	1777687808.8388731	1777687816.4342852	\N	["analyze mockup with GPT-4o vision  (0/4)", "loading mockup: /repo/boards/untitled-board-mom9qwhn/mockup/board.png", "  mockup loaded  (1/4)", "prompt: 3259 chars, 19 designs, 12 panels", "  image encoded  (2/4)", "\\u2192 calling GPT-4o vision (this takes ~10-20s)\\u2026", "  vision response received  (3/4)", "\\u2190 2377 chars received", "  done  (4/4)", "filled 33 / 33 prompt fields", "wrote 33 prompts to catalog  (spent ~$0.08 estimated)"]
5271c67519a3	Regenerate centerpiece	regen.centerpiece	centerpiece	done	1	\N	0.264	0.504	1777693918.3658779	1777693949.377793	\N	["centerpiece:centerpiece  (0/12)", "draw centerpiece/centerpiece (520x720, n=12, mode=img2img, provider=openai)", "  1777693947019__001.png  (1/12)", "  1777693947774__002.png  (2/12)", "  1777693948597__003.png  (3/12)", "  1777693949350__004.png  (4/12)", "promoted 1777693947019__001.png -> live/centerpiece/centerpiece", "promoted: 1777693947019__001.png  history+=4"]
200226e408c1	Regenerate panel_cleft_bot	regen.panels	panel_cleft_bot	done	1	\N	0.09	0.252	1777694002.6343622	1777694032.186151	\N	["panels:panel_cleft_bot  (0/6)", "draw panels/panel_cleft_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777694031351__005.png  (1/6)", "  1777694031606__006.png  (2/6)", "  1777694031864__007.png  (3/6)", "  1777694032122__008.png  (4/6)", "promoted 1777694031351__005.png -> live/panels/panel_cleft_bot", "promoted: 1777694031351__005.png  history+=4"]
bf5adde907e7	Regenerate panel_right_mid	regen.panels	panel_right_mid	done	1	\N	0.09	0.252	1777694048.830271	1777694081.074639	\N	["panels:panel_right_mid  (0/6)", "draw panels/panel_right_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777694079384__001.png  (1/6)", "  1777694080182__002.png  (2/6)", "  1777694080551__003.png  (3/6)", "  1777694080989__004.png  (4/6)", "promoted 1777694079384__001.png -> live/panels/panel_right_mid", "promoted: 1777694079384__001.png  history+=4"]
1197e8799d0a	Regenerate bottom_space_b	regen.spaces	bottom_space_b	done	1	\N	0.045	0.033	1777694118.2539334	1777694132.510659	\N	["spaces:bottom_space_b  (0/3)", "draw spaces/bottom_space_b (160x180, n=3, mode=txt2img, provider=openai)", "  1777694132319__004.png  (1/3)", "  1777694132404__005.png  (2/3)", "  1777694132479__006.png  (3/3)", "promoted 1777694132319__004.png -> live/spaces/bottom_space_b", "promoted: 1777694132319__004.png  history+=3"]
b007cefe1a09	Regenerate panel_cleft_top	regen.panels	panel_cleft_top	done	1	\N	0.09	0.066	1777694175.7650712	1777694198.2914648	\N	["panels:panel_cleft_top  (0/6)", "draw panels/panel_cleft_top (260x240, n=6, mode=img2img, provider=openai)", "  1777694197479__005.png  (1/6)", "  1777694197707__006.png  (2/6)", "  1777694197939__007.png  (3/6)", "  1777694198168__008.png  (4/6)", "promoted 1777694197479__005.png -> live/panels/panel_cleft_top", "promoted: 1777694197479__005.png  history+=4"]
50dfd2391f05	Regenerate panel_right_bot	regen.panels	panel_right_bot	done	1	\N	0.09	0.066	1777694232.2019746	1777694251.8088856	\N	["panels:panel_right_bot  (0/6)", "draw panels/panel_right_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777694251256__001.png  (1/6)", "  1777694251422__002.png  (2/6)", "  1777694251624__003.png  (3/6)", "  1777694251768__004.png  (4/6)", "promoted 1777694251256__001.png -> live/panels/panel_right_bot", "promoted: 1777694251256__001.png  history+=4"]
f3ba51c62f05	Regenerate panel_right_top	regen.panels	panel_right_top	done	1	\N	0.09	0.066	1777694291.441753	1777694313.5072823	\N	["panels:panel_right_top  (0/6)", "draw panels/panel_right_top (260x240, n=6, mode=img2img, provider=openai)", "  1777694312217__005.png  (1/6)", "  1777694312429__006.png  (2/6)", "  1777694312878__007.png  (3/6)", "  1777694313440__008.png  (4/6)", "promoted 1777694312217__005.png -> live/panels/panel_right_top", "promoted: 1777694312217__005.png  history+=4"]
a4df82a04d07	Composite preview	preview	untitled-board-mom9qwhn	done	1	\N	0	0	1777694333.531288	1777694335.1255999	\N	["compositing tiles  (0/48)", "  corner_tl@top_row.0  (1/48)", "  corner_tr@top_row.11  (2/48)", "  corner_bl@bottom_row.0  (3/48)", "  corner_br@bottom_row.11  (4/48)", "  top_banner_a@top_row.5  (5/48)", "  top_banner_b@top_row.7  (6/48)", "  top_space_a@top_row.1  (7/48)", "  top_space_a@top_row.4  (8/48)", "  top_space_a@top_row.8  (9/48)", "  top_space_b@top_row.2  (10/48)", "  top_space_b@top_row.6  (11/48)", "  top_space_b@top_row.9  (12/48)", "  top_space_c@top_row.3  (13/48)", "  top_space_c@top_row.10  (14/48)", "  bottom_banner_a@bottom_row.5  (15/48)", "  bottom_banner_b@bottom_row.6  (16/48)", "  bottom_space_a@bottom_row.1  (17/48)", "  bottom_space_a@bottom_row.4  (18/48)", "  bottom_space_b@bottom_row.2  (19/48)", "  bottom_space_b@bottom_row.10  (20/48)", "  bottom_space_c@bottom_row.3  (21/48)", "  bottom_space_c@bottom_row.8  (22/48)", "  bottom_space_d@bottom_row.9  (23/48)", "  bottom_battle@bottom_row.7  (24/48)", "  side_property@left_col.0  (25/48)", "  side_property@left_col.1  (26/48)", "  side_property@left_col.3  (27/48)", "  side_property@left_col.4  (28/48)", "  side_property@right_col.1  (29/48)", "  side_property@right_col.2  (30/48)", "  side_property@right_col.3  (31/48)", "  side_battle@left_col.2  (32/48)", "  side_battle@right_col.0  (33/48)", "  side_battle@right_col.4  (34/48)", "  top_battle@top_row.3  (35/48)", "  panel:panel_left_top  (36/48)", "  panel:panel_left_mid  (37/48)", "  panel:panel_left_bot  (38/48)", "  panel:panel_cleft_top  (39/48)", "  panel:panel_cleft_mid  (40/48)", "  panel:panel_cleft_bot  (41/48)", "  panel:panel_cright_top  (42/48)", "  panel:panel_cright_mid  (43/48)", "  panel:panel_cright_bot  (44/48)", "  panel:panel_right_top  (45/48)", "  panel:panel_right_mid  (46/48)", "  panel:panel_right_bot  (47/48)", "  centerpiece  (48/48)", "idle    -> /repo/boards/untitled-board-mom9qwhn/workspace/preview/board_idle.png", "active  -> /repo/boards/untitled-board-mom9qwhn/workspace/preview/board_active.png"]
1b2620635ef9	Regenerate panel_cleft_mid	regen.panels	panel_cleft_mid	done	1	\N	0.09	0.066	1777698168.3372076	1777698184.8982193	\N	["panels:panel_cleft_mid  (0/6)", "draw panels/panel_cleft_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777698184662__005.png  (1/6)", "  1777698184725__006.png  (2/6)", "  1777698184795__007.png  (3/6)", "  1777698184876__008.png  (4/6)", "promoted 1777698184662__005.png -> live/panels/panel_cleft_mid", "promoted: 1777698184662__005.png  history+=4"]
38e4ff9b4200	Regenerate panel_left_mid	regen.panels	panel_left_mid	done	1	\N	0.09	0.066	1777698220.3060935	1777698237.1819782	\N	["panels:panel_left_mid  (0/6)", "draw panels/panel_left_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777698236825__005.png  (1/6)", "  1777698236930__006.png  (2/6)", "  1777698237034__007.png  (3/6)", "  1777698237156__008.png  (4/6)", "promoted 1777698236825__005.png -> live/panels/panel_left_mid", "promoted: 1777698236825__005.png  history+=4"]
4611d24de322	Regenerate panel_left_bot	regen.panels	panel_left_bot	done	1	\N	0.09	0.066	1777698253.489362	1777698277.6453712	\N	["panels:panel_left_bot  (0/6)", "draw panels/panel_left_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777698277314__005.png  (1/6)", "  1777698277401__006.png  (2/6)", "  1777698277494__007.png  (3/6)", "  1777698277626__008.png  (4/6)", "promoted 1777698277314__005.png -> live/panels/panel_left_bot", "promoted: 1777698277314__005.png  history+=4"]
97e26d67ef86	Regenerate panel_cright_bot	regen.panels	panel_cright_bot	done	1	\N	0.09	0.066	1777698299.0366938	1777698336.0371826	\N	["panels:panel_cright_bot  (0/6)", "draw panels/panel_cright_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777698335274__005.png  (1/6)", "  1777698335372__006.png  (2/6)", "  1777698335636__007.png  (3/6)", "  1777698335828__008.png  (4/6)", "promoted 1777698335274__005.png -> live/panels/panel_cright_bot", "promoted: 1777698335274__005.png  history+=4"]
615e37700ea5	Regenerate top_space_a	regen.spaces	top_space_a	done	1	\N	0.045	0.033	1777698384.895018	1777698397.6192048	\N	["spaces:top_space_a  (0/3)", "draw spaces/top_space_a (160x180, n=3, mode=txt2img, provider=openai)", "  1777698397476__004.png  (1/3)", "  1777698397526__005.png  (2/3)", "  1777698397591__006.png  (3/3)", "promoted 1777698397476__004.png -> live/spaces/top_space_a", "promoted: 1777698397476__004.png  history+=3"]
d6848f7f6f75	Regenerate centerpiece	regen.centerpiece	centerpiece	done	1	\N	0.264	0.132	1777698466.3184679	1777698489.4971352	\N	["centerpiece:centerpiece  (0/12)", "draw centerpiece/centerpiece (520x720, n=12, mode=img2img, provider=openai)", "  1777698487337__005.png  (1/12)", "  1777698488039__006.png  (2/12)", "  1777698488711__007.png  (3/12)", "  1777698489474__008.png  (4/12)", "promoted 1777698487337__005.png -> live/centerpiece/centerpiece", "promoted: 1777698487337__005.png  history+=4"]
540f7aa46839	Regenerate centerpiece	regen.centerpiece	centerpiece	done	1	\N	0.264	0.132	1777698522.3421068	1777698542.503475	\N	["centerpiece:centerpiece  (0/12)", "draw centerpiece/centerpiece (520x720, n=12, mode=img2img, provider=openai)", "  1777698540290__009.png  (1/12)", "  1777698540961__010.png  (2/12)", "  1777698541701__011.png  (3/12)", "  1777698542482__012.png  (4/12)", "promoted 1777698540290__009.png -> live/centerpiece/centerpiece", "promoted: 1777698540290__009.png  history+=4"]
65bcfce93d38	Regenerate panel_left_mid	regen.panels	panel_left_mid	done	1	\N	0.09	0.066	1777698933.2108245	1777698959.5872786	\N	["panels:panel_left_mid  (0/6)", "draw panels/panel_left_mid (260x240, n=6, mode=inpaint, provider=openai)", "  1777698958712__009.png  (1/6)", "  1777698959031__010.png  (2/6)", "  1777698959232__011.png  (3/6)", "  1777698959477__012.png  (4/6)", "promoted 1777698958712__009.png -> live/panels/panel_left_mid", "promoted: 1777698958712__009.png  history+=4"]
ca727febb082	Regenerate panel_cright_top	regen.panels	panel_cright_top	done	1	\N	0.09	0.066	1777698568.8693674	1777698589.1127946	\N	["panels:panel_cright_top  (0/6)", "draw panels/panel_cright_top (260x240, n=6, mode=inpaint, provider=openai)", "  1777698588782__005.png  (1/6)", "  1777698588885__006.png  (2/6)", "  1777698588987__007.png  (3/6)", "  1777698589093__008.png  (4/6)", "promoted 1777698588782__005.png -> live/panels/panel_cright_top", "promoted: 1777698588782__005.png  history+=4"]
cd4ff0423785	Regenerate centerpiece	regen.centerpiece	centerpiece	done	1	\N	0.264	0.132	1777698605.047968	1777698633.1332448	\N	["centerpiece:centerpiece  (0/12)", "draw centerpiece/centerpiece (520x720, n=12, mode=img2img, provider=openai)", "  1777698630312__013.png  (1/12)", "  1777698631090__014.png  (2/12)", "  1777698632303__015.png  (3/12)", "  1777698633108__016.png  (4/12)", "promoted 1777698630312__013.png -> live/centerpiece/centerpiece", "promoted: 1777698630312__013.png  history+=4"]
411533823d59	Regenerate panel_cright_mid	regen.panels	panel_cright_mid	done	1	\N	0.09	0.066	1777698752.5312371	1777698778.809997	\N	["panels:panel_cright_mid  (0/6)", "draw panels/panel_cright_mid (260x240, n=6, mode=inpaint, provider=openai)", "  1777698777725__005.png  (1/6)", "  1777698778074__006.png  (2/6)", "  1777698778508__007.png  (3/6)", "  1777698778748__008.png  (4/6)", "promoted 1777698777725__005.png -> live/panels/panel_cright_mid", "promoted: 1777698777725__005.png  history+=4"]
33ae771c7792	Composite preview	preview	untitled-board-mom9qwhn	done	1	\N	0	0	1777699149.9397798	1777699151.0411236	\N	["compositing tiles  (0/48)", "  corner_tl@top_row.0  (1/48)", "  corner_tr@top_row.11  (2/48)", "  corner_bl@bottom_row.0  (3/48)", "  corner_br@bottom_row.11  (4/48)", "  top_banner_a@top_row.5  (5/48)", "  top_banner_b@top_row.7  (6/48)", "  top_space_a@top_row.1  (7/48)", "  top_space_a@top_row.4  (8/48)", "  top_space_a@top_row.8  (9/48)", "  top_space_b@top_row.2  (10/48)", "  top_space_b@top_row.6  (11/48)", "  top_space_b@top_row.9  (12/48)", "  top_space_c@top_row.3  (13/48)", "  top_space_c@top_row.10  (14/48)", "  bottom_banner_a@bottom_row.5  (15/48)", "  bottom_banner_b@bottom_row.6  (16/48)", "  bottom_space_a@bottom_row.1  (17/48)", "  bottom_space_a@bottom_row.4  (18/48)", "  bottom_space_b@bottom_row.2  (19/48)", "  bottom_space_b@bottom_row.10  (20/48)", "  bottom_space_c@bottom_row.3  (21/48)", "  bottom_space_c@bottom_row.8  (22/48)", "  bottom_space_d@bottom_row.9  (23/48)", "  bottom_battle@bottom_row.7  (24/48)", "  side_property@left_col.0  (25/48)", "  side_property@left_col.1  (26/48)", "  side_property@left_col.3  (27/48)", "  side_property@left_col.4  (28/48)", "  side_property@right_col.1  (29/48)", "  side_property@right_col.2  (30/48)", "  side_property@right_col.3  (31/48)", "  side_battle@left_col.2  (32/48)", "  side_battle@right_col.0  (33/48)", "  side_battle@right_col.4  (34/48)", "  top_battle@top_row.3  (35/48)", "  panel:panel_left_top  (36/48)", "  panel:panel_left_mid  (37/48)", "  panel:panel_left_bot  (38/48)", "  panel:panel_cleft_top  (39/48)", "  panel:panel_cleft_mid  (40/48)", "  panel:panel_cleft_bot  (41/48)", "  panel:panel_cright_top  (42/48)", "  panel:panel_cright_mid  (43/48)", "  panel:panel_cright_bot  (44/48)", "  panel:panel_right_top  (45/48)", "  panel:panel_right_mid  (46/48)", "  panel:panel_right_bot  (47/48)", "  centerpiece  (48/48)", "idle    -> /repo/boards/untitled-board-mom9qwhn/workspace/preview/board_idle.png", "active  -> /repo/boards/untitled-board-mom9qwhn/workspace/preview/board_active.png"]
580b61c7312e	Extract style from mockup	style	untitled-board-momdx7f5	done	1	\N	0	0	1777699450.118786	1777699452.0477765	\N	["style-lock  (0/3)", "extracting 36-color palette from board.png", "  palette  (1/3)", "  swatch  (2/3)", "  style-sheet  (3/3)", "palette  -> /repo/boards/untitled-board-momdx7f5/workspace/style/palette.json", "swatch   -> /repo/boards/untitled-board-momdx7f5/workspace/style/palette_swatch.png", "sheet    -> /repo/boards/untitled-board-momdx7f5/workspace/style/style_sheet.png"]
203173e20c49	Analyze mockup with GPT-4o	analyze	untitled-board-momdx7f5	done	1	\N	0.08	0.08	1777699467.0559459	1777699477.4612198	\N	["analyze mockup with GPT-4o vision  (0/4)", "loading mockup: /repo/boards/untitled-board-momdx7f5/mockup/board.png", "  mockup loaded  (1/4)", "prompt: 3259 chars, 19 designs, 12 panels", "  image encoded  (2/4)", "\\u2192 calling GPT-4o vision (this takes ~10-20s)\\u2026", "  vision response received  (3/4)", "\\u2190 2165 chars received", "  done  (4/4)", "filled 33 / 33 prompt fields", "wrote 33 prompts to catalog  (spent ~$0.08 estimated)"]
11ce21f37e42	Regenerate side_property	regen.spaces	side_property	done	1	\N	0.045	0.033	1777699537.6875494	1777699551.1947148	\N	["spaces:side_property  (0/3)", "draw spaces/side_property (180x144, n=3, mode=txt2img, provider=openai)", "  1777699551071__001.png  (1/3)", "  1777699551118__002.png  (2/3)", "  1777699551175__003.png  (3/3)", "promoted 1777699551071__001.png -> live/spaces/side_property", "promoted: 1777699551071__001.png  history+=3"]
e0f0ae7edd58	Regenerate centerpiece	regen.centerpiece	centerpiece	done	1	\N	0.264	0.132	1777699563.7333477	1777699585.986871	\N	["centerpiece:centerpiece  (0/12)", "draw centerpiece/centerpiece (520x720, n=12, mode=img2img, provider=openai)", "  1777699583461__001.png  (1/12)", "  1777699584260__002.png  (2/12)", "  1777699584972__003.png  (3/12)", "  1777699585946__004.png  (4/12)", "promoted 1777699583461__001.png -> live/centerpiece/centerpiece", "promoted: 1777699583461__001.png  history+=4"]
96f434c7b3a0	Regenerate centerpiece	regen.centerpiece	centerpiece	done	1	\N	0.264	0.132	1777700556.6403103	1777700586.44502	\N	["centerpiece:centerpiece  (0/12)", "draw centerpiece/centerpiece (520x720, n=12, mode=txt2img, provider=openai)", "  1777700579959__005.png  (1/12)", "  1777700581880__006.png  (2/12)", "  1777700584358__007.png  (3/12)", "  1777700586404__008.png  (4/12)", "promoted 1777700579959__005.png -> live/centerpiece/centerpiece", "promoted: 1777700579959__005.png  history+=4"]
86e51929fcda	Regenerate top_battle	regen.spaces	top_battle	done	1	\N	0.045	0.126	1777782892.747974	1777782913.8337133	\N	["spaces:top_battle  (0/3)", "draw spaces/top_battle (160x180, n=3, mode=txt2img, provider=openai)", "  1777782913715__001.png  (1/3)", "  1777782913766__002.png  (2/3)", "  1777782913814__003.png  (3/3)", "promoted 1777782913715__001.png -> live/spaces/top_battle", "promoted: 1777782913715__001.png  history+=3"]
a1079fa083a5	Regenerate panel_cright_mid	regen.panels	panel_cright_mid	done	1	\N	0.09	0.252	1777782944.7672887	1777782968.3521924	\N	["panels:panel_cright_mid  (0/6)", "draw panels/panel_cright_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777782967967__001.png  (1/6)", "  1777782968096__002.png  (2/6)", "  1777782968222__003.png  (3/6)", "  1777782968333__004.png  (4/6)", "promoted 1777782967967__001.png -> live/panels/panel_cright_mid", "promoted: 1777782967967__001.png  history+=4"]
b9815dc86869	Regenerate centerpiece	regen.centerpiece	centerpiece	done	1	\N	0.264	0.504	1777783005.4981651	1777783030.3516517	\N	["centerpiece:centerpiece  (0/12)", "draw centerpiece/centerpiece (520x720, n=12, mode=txt2img, provider=openai)", "  1777783027976__001.png  (1/12)", "  1777783028756__002.png  (2/12)", "  1777783029603__003.png  (3/12)", "  1777783030334__004.png  (4/12)", "promoted 1777783027976__001.png -> live/centerpiece/centerpiece", "promoted: 1777783027976__001.png  history+=4"]
5be7bb5ba4a3	Regenerate panel_cleft_mid	regen.panels	panel_cleft_mid	done	1	\N	0.09	0.252	1777783070.662862	1777783098.4152765	\N	["panels:panel_cleft_mid  (0/6)", "draw panels/panel_cleft_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777783098001__001.png  (1/6)", "  1777783098151__002.png  (2/6)", "  1777783098262__003.png  (3/6)", "  1777783098396__004.png  (4/6)", "promoted 1777783098001__001.png -> live/panels/panel_cleft_mid", "promoted: 1777783098001__001.png  history+=4"]
279eb3112802	Regenerate panel_cleft_mid	regen.panels	panel_cleft_mid	done	1	\N	0.09	0.252	1777823929.0610652	1777824277.1563938	\N	["panels:panel_cleft_mid  (0/6)", "draw panels/panel_cleft_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777824276922__001.png  (1/6)", "  1777824276996__002.png  (2/6)", "  1777824277068__003.png  (3/6)", "  1777824277138__004.png  (4/6)", "promoted 1777824276922__001.png -> live/panels/panel_cleft_mid", "promoted: 1777824276922__001.png  history+=4"]
4e28b2133131	Regenerate centerpiece	regen.centerpiece	centerpiece	done	1	\N	0.264	0.504	1777823987.8725393	1777824355.7671945	\N	["centerpiece:centerpiece  (0/12)", "draw centerpiece/centerpiece (520x720, n=12, mode=img2img, provider=openai)", "  1777824354302__001.png  (1/12)", "  1777824354770__002.png  (2/12)", "  1777824355265__003.png  (3/12)", "  1777824355751__004.png  (4/12)", "promoted 1777824354302__001.png -> live/centerpiece/centerpiece", "promoted: 1777824354302__001.png  history+=4"]
23e8f8825d89	Regenerate panel_cleft_mid	regen.panels	panel_cleft_mid	done	1	\N	0.09	0.252	1777824813.7568781	1777824887.241994	\N	["panels:panel_cleft_mid  (0/6)", "draw panels/panel_cleft_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777824887017__005.png  (1/6)", "  1777824887089__006.png  (2/6)", "  1777824887157__007.png  (3/6)", "  1777824887227__008.png  (4/6)", "promoted 1777824887017__005.png -> live/panels/panel_cleft_mid", "promoted: 1777824887017__005.png  history+=4"]
42ce3a64e07d	Regenerate panel_cright_mid	regen.panels	panel_cright_mid	done	1	\N	0.09	0.252	1777824822.42042	1777824955.8912673	\N	["panels:panel_cright_mid  (0/6)", "draw panels/panel_cright_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777824955642__001.png  (1/6)", "  1777824955720__002.png  (2/6)", "  1777824955794__003.png  (3/6)", "  1777824955874__004.png  (4/6)", "promoted 1777824955642__001.png -> live/panels/panel_cright_mid", "promoted: 1777824955642__001.png  history+=4"]
1cf024d9347f	Regenerate panel_left_bot	regen.panels	panel_left_bot	done	1	\N	0.09	0.252	1777824840.3455248	1777825019.5879622	\N	["panels:panel_left_bot  (0/6)", "draw panels/panel_left_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777825019345__001.png  (1/6)", "  1777825019421__002.png  (2/6)", "  1777825019498__003.png  (3/6)", "  1777825019571__004.png  (4/6)", "promoted 1777825019345__001.png -> live/panels/panel_left_bot", "promoted: 1777825019345__001.png  history+=4"]
ab59b6a91ba1	Regenerate panel_cleft_top	regen.panels	panel_cleft_top	done	1	\N	0.09	0.252	1777825097.78881	1777825198.5310805	\N	["panels:panel_cleft_top  (0/6)", "draw panels/panel_cleft_top (260x240, n=6, mode=img2img, provider=openai)", "  1777825198276__001.png  (1/6)", "  1777825198361__002.png  (2/6)", "  1777825198437__003.png  (3/6)", "  1777825198514__004.png  (4/6)", "promoted 1777825198276__001.png -> live/panels/panel_cleft_top", "promoted: 1777825198276__001.png  history+=4"]
fa06c9ab0bce	Regenerate panel_cleft_top	regen.panels	panel_cleft_top	done	1	\N	0.09	0.252	1777825297.4955325	1777825373.0252056	\N	["panels:panel_cleft_top  (0/6)", "draw panels/panel_cleft_top (260x240, n=6, mode=img2img, provider=openai)", "  1777825372791__005.png  (1/6)", "  1777825372864__006.png  (2/6)", "  1777825372940__007.png  (3/6)", "  1777825373011__008.png  (4/6)", "promoted 1777825372791__005.png -> live/panels/panel_cleft_top", "promoted: 1777825372791__005.png  history+=4"]
b64374b21253	Regenerate panel_cright_bot	regen.panels	panel_cright_bot	done	1	\N	0.09	0.252	1777825328.171247	1777825447.6552145	\N	["panels:panel_cright_bot  (0/6)", "draw panels/panel_cright_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777825446773__001.png  (1/6)", "  1777825447037__002.png  (2/6)", "  1777825447309__003.png  (3/6)", "  1777825447605__004.png  (4/6)", "promoted 1777825446773__001.png -> live/panels/panel_cright_bot", "promoted: 1777825446773__001.png  history+=4"]
98472e4a9560	Regenerate panel_left_top	regen.panels	panel_left_top	done	1	\N	0.09	0.252	1777825522.3777046	1777825588.017872	\N	["panels:panel_left_top  (0/6)", "draw panels/panel_left_top (260x240, n=6, mode=img2img, provider=openai)", "  1777825587797__001.png  (1/6)", "  1777825587869__002.png  (2/6)", "  1777825587938__003.png  (3/6)", "  1777825588006__004.png  (4/6)", "promoted 1777825587797__001.png -> live/panels/panel_left_top", "promoted: 1777825587797__001.png  history+=4"]
462b54dd8349	Regenerate panel_left_top	regen.panels	panel_left_top	done	1	\N	0.09	0.252	1777825642.4766026	1777825724.087706	\N	["panels:panel_left_top  (0/6)", "draw panels/panel_left_top (260x240, n=6, mode=img2img, provider=openai)", "  1777825723853__005.png  (1/6)", "  1777825723930__006.png  (2/6)", "  1777825724002__007.png  (3/6)", "  1777825724075__008.png  (4/6)", "promoted 1777825723853__005.png -> live/panels/panel_left_top", "promoted: 1777825723853__005.png  history+=4"]
69e2dd35192d	Regenerate panel_cleft_bot	regen.panels	panel_cleft_bot	done	1	\N	0.09	0.252	1777825691.8547995	1777825789.7861903	\N	["panels:panel_cleft_bot  (0/6)", "draw panels/panel_cleft_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777825789571__001.png  (1/6)", "  1777825789635__002.png  (2/6)", "  1777825789702__003.png  (3/6)", "  1777825789774__004.png  (4/6)", "promoted 1777825789571__001.png -> live/panels/panel_cleft_bot", "promoted: 1777825789571__001.png  history+=4"]
239e46d7cff1	Regenerate panel_cright_bot	regen.panels	panel_cright_bot	done	1	\N	0.09	0.252	1777825841.7380772	1777825926.847196	\N	["panels:panel_cright_bot  (0/6)", "draw panels/panel_cright_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777825926619__005.png  (1/6)", "  1777825926692__006.png  (2/6)", "  1777825926767__007.png  (3/6)", "  1777825926834__008.png  (4/6)", "promoted 1777825926619__005.png -> live/panels/panel_cright_bot", "promoted: 1777825926619__005.png  history+=4"]
2013b82b1e2b	Regenerate panel_left_mid	regen.panels	panel_left_mid	done	1	\N	0.09	0.252	1777825891.6284251	1777826004.6150374	\N	["panels:panel_left_mid  (0/6)", "draw panels/panel_left_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777826004367__001.png  (1/6)", "  1777826004443__002.png  (2/6)", "  1777826004522__003.png  (3/6)", "  1777826004599__004.png  (4/6)", "promoted 1777826004367__001.png -> live/panels/panel_left_mid", "promoted: 1777826004367__001.png  history+=4"]
a8257b3d061b	Regenerate panel_cright_top	regen.panels	panel_cright_top	done	1	\N	0.09	0.252	1777825987.7748582	1777826080.455778	\N	["panels:panel_cright_top  (0/6)", "draw panels/panel_cright_top (260x240, n=6, mode=img2img, provider=openai)", "  1777826080212__001.png  (1/6)", "  1777826080291__002.png  (2/6)", "  1777826080365__003.png  (3/6)", "  1777826080443__004.png  (4/6)", "promoted 1777826080212__001.png -> live/panels/panel_cright_top", "promoted: 1777826080212__001.png  history+=4"]
a9ac4dbb1ae4	Regenerate panel_cright_top	regen.panels	panel_cright_top	done	1	\N	0.09	0.252	1777826149.6146708	1777826268.5344512	\N	["panels:panel_cright_top  (0/6)", "draw panels/panel_cright_top (260x240, n=6, mode=img2img, provider=openai)", "  1777826267429__005.png  (1/6)", "  1777826267798__006.png  (2/6)", "  1777826268133__007.png  (3/6)", "  1777826268483__008.png  (4/6)", "promoted 1777826267429__005.png -> live/panels/panel_cright_top", "promoted: 1777826267429__005.png  history+=4"]
6aefe4f5ba9f	Regenerate bottom_space_d	regen.spaces	bottom_space_d	done	1	\N	0.045	0.126	1777826388.962979	1777826465.4550238	\N	["spaces:bottom_space_d  (0/3)", "draw spaces/bottom_space_d (160x180, n=3, mode=txt2img, provider=openai)", "  1777826465363__001.png  (1/3)", "  1777826465401__002.png  (2/3)", "  1777826465442__003.png  (3/3)", "promoted 1777826465363__001.png -> live/spaces/bottom_space_d", "promoted: 1777826465363__001.png  history+=3"]
bb32701f915c	Regenerate panel_right_top	regen.panels	panel_right_top	done	1	\N	0.09	0.252	1777826215.6457033	1777826351.855514	\N	["panels:panel_right_top  (0/6)", "draw panels/panel_right_top (260x240, n=6, mode=img2img, provider=openai)", "  1777826351387__001.png  (1/6)", "  1777826351483__002.png  (2/6)", "  1777826351676__003.png  (3/6)", "  1777826351807__004.png  (4/6)", "promoted 1777826351387__001.png -> live/panels/panel_right_top", "promoted: 1777826351387__001.png  history+=4"]
97fded30bc69	Regenerate panel_right_mid	regen.panels	panel_right_mid	done	1	\N	0.09	0.252	1777844318.7806938	1777844385.4610684	\N	["panels:panel_right_mid  (0/6)", "draw panels/panel_right_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777844385108__001.png  (1/6)", "  1777844385179__002.png  (2/6)", "  1777844385372__003.png  (3/6)", "  1777844385448__004.png  (4/6)", "promoted 1777844385108__001.png -> live/panels/panel_right_mid", "promoted: 1777844385108__001.png  history+=4"]
d931b54fda57	Regenerate panel_right_bot	regen.panels	panel_right_bot	done	1	\N	0.09	0.252	1777844412.9967165	1777844484.580533	\N	["panels:panel_right_bot  (0/6)", "draw panels/panel_right_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777844484349__001.png  (1/6)", "  1777844484420__002.png  (2/6)", "  1777844484491__003.png  (3/6)", "  1777844484565__004.png  (4/6)", "promoted 1777844484349__001.png -> live/panels/panel_right_bot", "promoted: 1777844484349__001.png  history+=4"]
1f4e3d375aad	Regenerate panel_right_top	regen.panels	panel_right_top	done	1	\N	0.09	0.252	1777844542.1195517	1777844606.7369187	\N	["panels:panel_right_top  (0/6)", "draw panels/panel_right_top (260x240, n=6, mode=img2img, provider=openai)", "  1777844606511__005.png  (1/6)", "  1777844606580__006.png  (2/6)", "  1777844606651__007.png  (3/6)", "  1777844606722__008.png  (4/6)", "promoted 1777844606511__005.png -> live/panels/panel_right_top", "promoted: 1777844606511__005.png  history+=4"]
f65012f958db	Regenerate panel_right_top	regen.panels	panel_right_top	done	1	\N	0.09	0.252	1777844708.000642	1777844784.1289248	\N	["panels:panel_right_top  (0/6)", "draw panels/panel_right_top (260x240, n=6, mode=img2img, provider=openai)", "  1777844783903__009.png  (1/6)", "  1777844783973__010.png  (2/6)", "  1777844784044__011.png  (3/6)", "  1777844784116__012.png  (4/6)", "promoted 1777844783903__009.png -> live/panels/panel_right_top", "promoted: 1777844783903__009.png  history+=4"]
88831dd3c80e	Regenerate panel_left_bot	regen.panels	panel_left_bot	done	1	\N	0.09	0.252	1777844765.3329976	1777844857.6686835	\N	["panels:panel_left_bot  (0/6)", "draw panels/panel_left_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777844856775__005.png  (1/6)", "  1777844857042__006.png  (2/6)", "  1777844857324__007.png  (3/6)", "  1777844857620__008.png  (4/6)", "promoted 1777844856775__005.png -> live/panels/panel_left_bot", "promoted: 1777844856775__005.png  history+=4"]
904cd774b2a7	Regenerate panel_left_bot	regen.panels	panel_left_bot	done	1	\N	0.09	0.252	1777845038.4814746	1777845103.814398	\N	["panels:panel_left_bot  (0/6)", "draw panels/panel_left_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777845103569__009.png  (1/6)", "  1777845103644__010.png  (2/6)", "  1777845103722__011.png  (3/6)", "  1777845103803__012.png  (4/6)", "promoted 1777845103569__009.png -> live/panels/panel_left_bot", "promoted: 1777845103569__009.png  history+=4"]
a7c6d7119e90	Regenerate panel_right_top	regen.panels	panel_right_top	done	1	\N	0.09	0.252	1777845070.8654728	1777845170.872878	\N	["panels:panel_right_top  (0/6)", "draw panels/panel_right_top (260x240, n=6, mode=img2img, provider=openai)", "  1777845170638__013.png  (1/6)", "  1777845170712__014.png  (2/6)", "  1777845170782__015.png  (3/6)", "  1777845170862__016.png  (4/6)", "promoted 1777845170638__013.png -> live/panels/panel_right_top", "promoted: 1777845170638__013.png  history+=4"]
98215f033073	Regenerate panel_right_bot	regen.panels	panel_right_bot	done	1	\N	0.09	0.252	1777845138.5761926	1777845234.9538193	\N	["panels:panel_right_bot  (0/6)", "draw panels/panel_right_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777845234720__005.png  (1/6)", "  1777845234795__006.png  (2/6)", "  1777845234867__007.png  (3/6)", "  1777845234938__008.png  (4/6)", "promoted 1777845234720__005.png -> live/panels/panel_right_bot", "promoted: 1777845234720__005.png  history+=4"]
eee1801ada6f	Regenerate corner_bl	regen.spaces	corner_bl	done	1	\N	0.045	0.126	1777845269.2329736	1777845333.926173	\N	["spaces:corner_bl  (0/3)", "draw spaces/corner_bl (160x180, n=3, mode=txt2img, provider=openai)", "  1777845333831__004.png  (1/3)", "  1777845333874__005.png  (2/3)", "  1777845333912__006.png  (3/3)", "promoted 1777845333831__004.png -> live/spaces/corner_bl", "promoted: 1777845333831__004.png  history+=3"]
d27abf10bde2	Regenerate panel_cright_bot	regen.panels	panel_cright_bot	done	1	\N	0.09	0	1777845637.2109005	1777846205.0904472	\N	["panels:panel_cright_bot  (0/6)", "draw panels/panel_cright_bot (260x240, n=6, mode=img2img, provider=openai)", "FAIL panels/panel_cright_bot: The read operation timed out", "promoted: (none)  history+=0"]
49bf03801ff0	Regenerate panel_right_top	regen.panels	panel_right_top	done	1	\N	0.09	0.252	1777846643.696941	1777846721.0395315	\N	["panels:panel_right_top  (0/6)", "draw panels/panel_right_top (260x240, n=6, mode=img2img, provider=openai)", "  1777846720797__017.png  (1/6)", "  1777846720887__018.png  (2/6)", "  1777846720957__019.png  (3/6)", "  1777846721027__020.png  (4/6)", "promoted 1777846720797__017.png -> live/panels/panel_right_top", "promoted: 1777846720797__017.png  history+=4"]
8293f766e230	Regenerate panel_right_top	regen.panels	panel_right_top	done	1	\N	0.09	0.252	1777846810.3016338	1777846878.2657952	\N	["panels:panel_right_top  (0/6)", "draw panels/panel_right_top (260x240, n=6, mode=img2img, provider=openai)", "  1777846878006__021.png  (1/6)", "  1777846878093__022.png  (2/6)", "  1777846878173__023.png  (3/6)", "  1777846878251__024.png  (4/6)", "promoted 1777846878006__021.png -> live/panels/panel_right_top", "promoted: 1777846878006__021.png  history+=4"]
24af72125496	Regenerate panel_cright_mid	regen.panels	panel_cright_mid	done	1	\N	0.09	0.252	1777847056.1739533	1777847123.2916214	\N	["panels:panel_cright_mid  (0/6)", "draw panels/panel_cright_mid (260x240, n=6, mode=img2img, provider=openai)", "  1777847123061__005.png  (1/6)", "  1777847123133__006.png  (2/6)", "  1777847123209__007.png  (3/6)", "  1777847123280__008.png  (4/6)", "promoted 1777847123061__005.png -> live/panels/panel_cright_mid", "promoted: 1777847123061__005.png  history+=4"]
7c90a2fcb375	Regenerate panel_cright_bot	regen.panels	panel_cright_bot	done	1	\N	0.09	0.252	1777847255.7292562	1777847316.5022047	\N	["panels:panel_cright_bot  (0/6)", "draw panels/panel_cright_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777847316270__009.png  (1/6)", "  1777847316341__010.png  (2/6)", "  1777847316414__011.png  (3/6)", "  1777847316488__012.png  (4/6)", "promoted 1777847316270__009.png -> live/panels/panel_cright_bot", "promoted: 1777847316270__009.png  history+=4"]
6f80b85018e9	Regenerate panel_cright_bot	regen.panels	panel_cright_bot	done	1	\N	0.09	0.252	1777847626.0553985	1777847695.1287646	\N	["panels:panel_cright_bot  (0/6)", "draw panels/panel_cright_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777847694869__013.png  (1/6)", "  1777847694949__014.png  (2/6)", "  1777847695031__015.png  (3/6)", "  1777847695117__016.png  (4/6)", "promoted 1777847694869__013.png -> live/panels/panel_cright_bot", "promoted: 1777847694869__013.png  history+=4"]
12ca92877643	Regenerate panel_cright_bot	regen.panels	panel_cright_bot	done	1	\N	0.09	0.252	1777847800.7703762	1777847881.7749739	\N	["panels:panel_cright_bot  (0/6)", "draw panels/panel_cright_bot (260x240, n=6, mode=img2img, provider=openai)", "  1777847881430__017.png  (1/6)", "  1777847881536__018.png  (2/6)", "  1777847881650__019.png  (3/6)", "  1777847881755__020.png  (4/6)", "promoted 1777847881430__017.png -> live/panels/panel_cright_bot", "promoted: 1777847881430__017.png  history+=4"]
132f4c6f399d	Composite preview	preview	untitled-board-mom4pk3y	done	1	\N	0	0	1777864065.6948254	1777864067.4887273	\N	["compositing tiles  (0/48)", "  corner_tl@top_row.0  (1/48)", "  corner_tr@top_row.11  (2/48)", "  corner_bl@bottom_row.0  (3/48)", "  corner_br@bottom_row.11  (4/48)", "  top_banner_a@top_row.5  (5/48)", "  top_banner_b@top_row.7  (6/48)", "  top_space_a@top_row.1  (7/48)", "  top_space_a@top_row.4  (8/48)", "  top_space_a@top_row.8  (9/48)", "  top_space_b@top_row.2  (10/48)", "  top_space_b@top_row.6  (11/48)", "  top_space_b@top_row.9  (12/48)", "  top_space_c@top_row.3  (13/48)", "  top_space_c@top_row.10  (14/48)", "  bottom_banner_a@bottom_row.5  (15/48)", "  bottom_banner_b@bottom_row.6  (16/48)", "  bottom_space_a@bottom_row.1  (17/48)", "  bottom_space_a@bottom_row.4  (18/48)", "  bottom_space_b@bottom_row.2  (19/48)", "  bottom_space_b@bottom_row.10  (20/48)", "  bottom_space_c@bottom_row.3  (21/48)", "  bottom_space_c@bottom_row.8  (22/48)", "  bottom_space_d@bottom_row.9  (23/48)", "  bottom_battle@bottom_row.7  (24/48)", "  side_property@left_col.0  (25/48)", "  side_property@left_col.1  (26/48)", "  side_property@left_col.3  (27/48)", "  side_property@left_col.4  (28/48)", "  side_property@right_col.1  (29/48)", "  side_property@right_col.2  (30/48)", "  side_property@right_col.3  (31/48)", "  side_battle@left_col.2  (32/48)", "  side_battle@right_col.0  (33/48)", "  side_battle@right_col.4  (34/48)", "  top_battle@top_row.3  (35/48)", "  panel:panel_left_top  (36/48)", "  panel:panel_left_mid  (37/48)", "  panel:panel_left_bot  (38/48)", "  panel:panel_cleft_top  (39/48)", "  panel:panel_cleft_mid  (40/48)", "  panel:panel_cleft_bot  (41/48)", "  panel:panel_cright_top  (42/48)", "  panel:panel_cright_mid  (43/48)", "  panel:panel_cright_bot  (44/48)", "  panel:panel_right_top  (45/48)", "  panel:panel_right_mid  (46/48)", "  panel:panel_right_bot  (47/48)", "  centerpiece  (48/48)", "idle    -> /repo/data/boards/untitled-board-mom4pk3y/workspace/preview/board_idle.png", "active  -> /repo/data/boards/untitled-board-mom4pk3y/workspace/preview/board_active.png"]
1dd1c27fbb1d	Composite preview	preview	untitled-board-mokzf8v7	done	1	\N	0	0	1777864075.8099573	1777864077.142295	\N	["compositing tiles  (0/48)", "  corner_tl@top_row.0  (1/48)", "  corner_tr@top_row.11  (2/48)", "  corner_bl@bottom_row.0  (3/48)", "  corner_br@bottom_row.11  (4/48)", "  top_banner_a@top_row.5  (5/48)", "  top_banner_b@top_row.7  (6/48)", "  top_space_a@top_row.1  (7/48)", "  top_space_a@top_row.4  (8/48)", "  top_space_a@top_row.8  (9/48)", "  top_space_b@top_row.2  (10/48)", "  top_space_b@top_row.6  (11/48)", "  top_space_b@top_row.9  (12/48)", "  top_space_c@top_row.3  (13/48)", "  top_space_c@top_row.10  (14/48)", "  bottom_banner_a@bottom_row.5  (15/48)", "  bottom_banner_b@bottom_row.6  (16/48)", "  bottom_space_a@bottom_row.1  (17/48)", "  bottom_space_a@bottom_row.4  (18/48)", "  bottom_space_b@bottom_row.2  (19/48)", "  bottom_space_b@bottom_row.10  (20/48)", "  bottom_space_c@bottom_row.3  (21/48)", "  bottom_space_c@bottom_row.8  (22/48)", "  bottom_space_d@bottom_row.9  (23/48)", "  bottom_battle@bottom_row.7  (24/48)", "  side_property@left_col.0  (25/48)", "  side_property@left_col.1  (26/48)", "  side_property@left_col.3  (27/48)", "  side_property@left_col.4  (28/48)", "  side_property@right_col.1  (29/48)", "  side_property@right_col.2  (30/48)", "  side_property@right_col.3  (31/48)", "  side_battle@left_col.2  (32/48)", "  side_battle@right_col.0  (33/48)", "  side_battle@right_col.4  (34/48)", "  top_battle@top_row.3  (35/48)", "  panel:panel_left_top  (36/48)", "  panel:panel_left_mid  (37/48)", "  panel:panel_left_bot  (38/48)", "  panel:panel_cleft_top  (39/48)", "  panel:panel_cleft_mid  (40/48)", "  panel:panel_cleft_bot  (41/48)", "  panel:panel_cright_top  (42/48)", "  panel:panel_cright_mid  (43/48)", "  panel:panel_cright_bot  (44/48)", "  panel:panel_right_top  (45/48)", "  panel:panel_right_mid  (46/48)", "  panel:panel_right_bot  (47/48)", "  centerpiece  (48/48)", "idle    -> /repo/data/boards/untitled-board-mokzf8v7/workspace/preview/board_idle.png", "active  -> /repo/data/boards/untitled-board-mokzf8v7/workspace/preview/board_active.png"]
1fd8b77fe7b0	Composite preview	preview	untitled-board-momdx7f5	done	1	\N	0	0	1777864116.2021348	1777864116.796012	\N	["compositing tiles  (0/48)", "  corner_tl@top_row.0  (1/48)", "  corner_tr@top_row.11  (2/48)", "  corner_bl@bottom_row.0  (3/48)", "  corner_br@bottom_row.11  (4/48)", "  top_banner_a@top_row.5  (5/48)", "  top_banner_b@top_row.7  (6/48)", "  top_space_a@top_row.1  (7/48)", "  top_space_a@top_row.4  (8/48)", "  top_space_a@top_row.8  (9/48)", "  top_space_b@top_row.2  (10/48)", "  top_space_b@top_row.6  (11/48)", "  top_space_b@top_row.9  (12/48)", "  top_space_c@top_row.3  (13/48)", "  top_space_c@top_row.10  (14/48)", "  bottom_banner_a@bottom_row.5  (15/48)", "  bottom_banner_b@bottom_row.6  (16/48)", "  bottom_space_a@bottom_row.1  (17/48)", "  bottom_space_a@bottom_row.4  (18/48)", "  bottom_space_b@bottom_row.2  (19/48)", "  bottom_space_b@bottom_row.10  (20/48)", "  bottom_space_c@bottom_row.3  (21/48)", "  bottom_space_c@bottom_row.8  (22/48)", "  bottom_space_d@bottom_row.9  (23/48)", "  bottom_battle@bottom_row.7  (24/48)", "  side_property@left_col.0  (25/48)", "  side_property@left_col.1  (26/48)", "  side_property@left_col.3  (27/48)", "  side_property@left_col.4  (28/48)", "  side_property@right_col.1  (29/48)", "  side_property@right_col.2  (30/48)", "  side_property@right_col.3  (31/48)", "skip space:side_battle (no live)", "  side_battle  (32/48)", "  side_battle  (33/48)", "  side_battle  (34/48)", "  top_battle@top_row.3  (35/48)", "skip panel:panel_left_top (no live)", "  panel_left_top  (36/48)", "skip panel:panel_left_mid (no live)", "  panel_left_mid  (37/48)", "skip panel:panel_left_bot (no live)", "  panel_left_bot  (38/48)", "skip panel:panel_cleft_top (no live)", "  panel_cleft_top  (39/48)", "  panel:panel_cleft_mid  (40/48)", "skip panel:panel_cleft_bot (no live)", "  panel_cleft_bot  (41/48)", "skip panel:panel_cright_top (no live)", "  panel_cright_top  (42/48)", "  panel:panel_cright_mid  (43/48)", "skip panel:panel_cright_bot (no live)", "  panel_cright_bot  (44/48)", "skip panel:panel_right_top (no live)", "  panel_right_top  (45/48)", "skip panel:panel_right_mid (no live)", "  panel_right_mid  (46/48)", "skip panel:panel_right_bot (no live)", "  panel_right_bot  (47/48)", "  centerpiece  (48/48)", "idle    -> /repo/data/boards/untitled-board-momdx7f5/workspace/preview/board_idle.png", "active  -> /repo/data/boards/untitled-board-momdx7f5/workspace/preview/board_active.png", "composited with 11 missing tile(s): space:side_battle, panel:panel_left_top, panel:panel_left_mid, panel:panel_left_bot, panel:panel_cleft_top, panel:panel_cleft_bot, panel:panel_cright_top, panel:panel_cright_bot, panel:panel_right_top, panel:panel_right_mid, panel:panel_right_bot"]
c58b78b8f113	Regenerate panel_cright_top	regen.panels	panel_cright_top	done	1	\N	0.045	0.126	1777864783.7898593	1777864809.5452552	\N	["panels:panel_cright_top  (0/3)", "draw panels/panel_cright_top (260x240, n=3, mode=img2img, provider=openai)", "  1777864809306__001.png  (1/3)", "  1777864809418__002.png  (2/3)", "  1777864809523__003.png  (3/3)", "promoted 1777864809306__001.png -> live/panels/panel_cright_top", "promoted: 1777864809306__001.png  history+=3"]
63013130cb3d	Regenerate panel_cleft_top	regen.panels	panel_cleft_top	done	1	\N	0.045	0.126	1777864834.634181	1777864856.8274083	\N	["panels:panel_cleft_top  (0/3)", "draw panels/panel_cleft_top (260x240, n=3, mode=img2img, provider=openai)", "  1777864856627__001.png  (1/3)", "  1777864856725__002.png  (2/3)", "  1777864856814__003.png  (3/3)", "promoted 1777864856627__001.png -> live/panels/panel_cleft_top", "promoted: 1777864856627__001.png  history+=3"]
aff337ae94e6	Generate 9 missing assets	generate.all	untitled-board-momdx7f5	killed	1	\N	0.40499999999999997	0	1777865375.43746	1777865401.1483777	\N	["generate missing spaces (1)  (0/1)", "spaces:side_battle  (n=3)", "draw spaces/side_battle (180x144, n=3, mode=txt2img, provider=openai)", "\\u2190 cancel requested by user", "\\u2190 cancel requested by user", "\\u2190 cancel requested by user", "\\u2190 cancel requested by user", "\\u2190 cancel requested by user", "  1777865399983__001.png", "  1777865400392__002.png", "  1777865400938__003.png", "promoted 1777865399983__001.png -> live/spaces/side_battle", "  side_battle  (1/1)"]
b8c6a0a984c3	Composite preview	preview	untitled-board-mom9qwhn	done	1	\N	0	0	1777866463.7586765	1777866464.9689436	\N	["compositing tiles  (0/48)", "  corner_tl@top_row.0  (1/48)", "  corner_tr@top_row.11  (2/48)", "  corner_bl@bottom_row.0  (3/48)", "  corner_br@bottom_row.11  (4/48)", "  top_banner_a@top_row.5  (5/48)", "  top_banner_b@top_row.7  (6/48)", "  top_space_a@top_row.1  (7/48)", "  top_space_a@top_row.4  (8/48)", "  top_space_a@top_row.8  (9/48)", "  top_space_b@top_row.2  (10/48)", "  top_space_b@top_row.6  (11/48)", "  top_space_b@top_row.9  (12/48)", "  top_space_c@top_row.3  (13/48)", "  top_space_c@top_row.10  (14/48)", "  bottom_banner_a@bottom_row.5  (15/48)", "  bottom_banner_b@bottom_row.6  (16/48)", "  bottom_space_a@bottom_row.1  (17/48)", "  bottom_space_a@bottom_row.4  (18/48)", "  bottom_space_b@bottom_row.2  (19/48)", "  bottom_space_b@bottom_row.10  (20/48)", "  bottom_space_c@bottom_row.3  (21/48)", "  bottom_space_c@bottom_row.8  (22/48)", "  bottom_space_d@bottom_row.9  (23/48)", "  bottom_battle@bottom_row.7  (24/48)", "  side_property@left_col.0  (25/48)", "  side_property@left_col.1  (26/48)", "  side_property@left_col.3  (27/48)", "  side_property@left_col.4  (28/48)", "  side_property@right_col.1  (29/48)", "  side_property@right_col.2  (30/48)", "  side_property@right_col.3  (31/48)", "  side_battle@left_col.2  (32/48)", "  side_battle@right_col.0  (33/48)", "  side_battle@right_col.4  (34/48)", "  top_battle@top_row.3  (35/48)", "  panel:panel_left_top  (36/48)", "  panel:panel_left_mid  (37/48)", "  panel:panel_left_bot  (38/48)", "  panel:panel_cleft_top  (39/48)", "  panel:panel_cleft_mid  (40/48)", "  panel:panel_cleft_bot  (41/48)", "  panel:panel_cright_top  (42/48)", "  panel:panel_cright_mid  (43/48)", "  panel:panel_cright_bot  (44/48)", "  panel:panel_right_top  (45/48)", "  panel:panel_right_mid  (46/48)", "  panel:panel_right_bot  (47/48)", "  centerpiece  (48/48)", "idle    -> /repo/data/boards/untitled-board-mom9qwhn/workspace/preview/board_idle.png", "active  -> /repo/data/boards/untitled-board-mom9qwhn/workspace/preview/board_active.png"]
b6ec2bf5115a	Extract style from mockup	style	demo-board	done	1	\N	0	0	1777822179.4559653	1777822181.128285	\N	["style-lock  (0/3)", "extracting 36-color palette from board.png", "  palette  (1/3)", "  swatch  (2/3)", "  style-sheet  (3/3)", "palette  -> /repo/data/boards/untitled-board-mopxc3av/workspace/style/palette.json", "swatch   -> /repo/data/boards/untitled-board-mopxc3av/workspace/style/palette_swatch.png", "sheet    -> /repo/data/boards/untitled-board-mopxc3av/workspace/style/style_sheet.png"]
793a7aa3f92f	Analyze mockup with GPT-4o	analyze	demo-board	done	1	\N	0.08	0.08	1777822212.4074173	1777822220.3364177	\N	["analyze mockup with GPT-4o vision  (0/4)", "loading mockup: /repo/data/boards/untitled-board-mopxc3av/mockup/board.png", "  mockup loaded  (1/4)", "prompt: 3259 chars, 19 designs, 12 panels", "  image encoded  (2/4)", "\\u2192 calling GPT-4o vision (this takes ~10-20s)\\u2026", "  vision response received  (3/4)", "\\u2190 1979 chars received", "  done  (4/4)", "filled 33 / 33 prompt fields", "wrote 33 prompts to catalog  (spent ~$0.08 estimated)"]
e992e4eb99f5	Composite preview	preview	demo-board	done	1	\N	0	0	1777848058.3746195	1777848058.9911206	\N	["compositing tiles  (0/48)", "  corner_tl@top_row.0  (1/48)", "  corner_tr@top_row.11  (2/48)", "  corner_bl@bottom_row.0  (3/48)", "  corner_br@bottom_row.11  (4/48)", "  top_banner_a@top_row.5  (5/48)", "  top_banner_b@top_row.7  (6/48)", "  top_space_a@top_row.1  (7/48)", "  top_space_a@top_row.4  (8/48)", "  top_space_a@top_row.8  (9/48)", "  top_space_b@top_row.2  (10/48)", "  top_space_b@top_row.6  (11/48)", "  top_space_b@top_row.9  (12/48)", "  top_space_c@top_row.3  (13/48)", "  top_space_c@top_row.10  (14/48)", "  bottom_banner_a@bottom_row.5  (15/48)", "  bottom_banner_b@bottom_row.6  (16/48)", "  bottom_space_a@bottom_row.1  (17/48)", "  bottom_space_a@bottom_row.4  (18/48)", "  bottom_space_b@bottom_row.2  (19/48)", "  bottom_space_b@bottom_row.10  (20/48)", "  bottom_space_c@bottom_row.3  (21/48)", "  bottom_space_c@bottom_row.8  (22/48)", "  bottom_space_d@bottom_row.9  (23/48)", "  bottom_battle@bottom_row.7  (24/48)", "  side_property@left_col.0  (25/48)", "  side_property@left_col.1  (26/48)", "  side_property@left_col.3  (27/48)", "  side_property@left_col.4  (28/48)", "  side_property@right_col.1  (29/48)", "  side_property@right_col.2  (30/48)", "  side_property@right_col.3  (31/48)", "  side_battle@left_col.2  (32/48)", "  side_battle@right_col.0  (33/48)", "  side_battle@right_col.4  (34/48)", "  top_battle@top_row.3  (35/48)", "  panel:panel_left_top  (36/48)", "  panel:panel_left_mid  (37/48)", "  panel:panel_left_bot  (38/48)", "  panel:panel_cleft_top  (39/48)", "  panel:panel_cleft_mid  (40/48)", "  panel:panel_cleft_bot  (41/48)", "  panel:panel_cright_top  (42/48)", "  panel:panel_cright_mid  (43/48)", "  panel:panel_cright_bot  (44/48)", "  panel:panel_right_top  (45/48)", "  panel:panel_right_mid  (46/48)", "  panel:panel_right_bot  (47/48)", "  centerpiece  (48/48)", "idle    -> /repo/data/boards/untitled-board-mopxc3av/workspace/preview/board_idle.png", "active  -> /repo/data/boards/untitled-board-mopxc3av/workspace/preview/board_active.png"]
ffe3d8e3f1f2	Generate 31 missing assets	generate.all	demo-board	killed	1	\N	1.935	0	1777822267.8140779	1777824202.7599473	\N	["generate missing spaces (19)  (0/19)", "spaces:corner_tl  (n=3)", "draw spaces/corner_tl (160x180, n=3, mode=txt2img, provider=openai)", "  1777822349039__001.png", "  1777822349127__002.png", "  1777822349212__003.png", "promoted 1777822349039__001.png -> live/spaces/corner_tl", "  corner_tl  (1/19)", "spaces:corner_tr  (n=3)", "draw spaces/corner_tr (160x180, n=3, mode=txt2img, provider=openai)", "  1777822500126__001.png", "  1777822500265__002.png", "  1777822500429__003.png", "promoted 1777822500126__001.png -> live/spaces/corner_tr", "  corner_tr  (2/19)", "spaces:corner_bl  (n=3)", "draw spaces/corner_bl (160x180, n=3, mode=txt2img, provider=openai)", "  1777822581814__001.png", "  1777822581954__002.png", "  1777822582196__003.png", "promoted 1777822581814__001.png -> live/spaces/corner_bl", "  corner_bl  (3/19)", "spaces:corner_br  (n=3)", "draw spaces/corner_br (160x180, n=3, mode=txt2img, provider=openai)", "  1777822669625__001.png", "  1777822669955__002.png", "  1777822670420__003.png", "promoted 1777822669625__001.png -> live/spaces/corner_br", "  corner_br  (4/19)", "spaces:top_banner_a  (n=3)", "draw spaces/top_banner_a (160x180, n=3, mode=txt2img, provider=openai)", "  1777822750329__001.png", "  1777822750841__002.png", "  1777822751181__003.png", "promoted 1777822750329__001.png -> live/spaces/top_banner_a", "  top_banner_a  (5/19)", "spaces:top_banner_b  (n=3)", "draw spaces/top_banner_b (160x180, n=3, mode=txt2img, provider=openai)", "  1777822836190__001.png", "  1777822836235__002.png", "  1777822836284__003.png", "promoted 1777822836190__001.png -> live/spaces/top_banner_b", "  top_banner_b  (6/19)", "spaces:top_space_a  (n=3)", "draw spaces/top_space_a (160x180, n=3, mode=txt2img, provider=openai)", "\\u2190 cancel requested by user", "  1777822918326__001.png", "  1777822918366__002.png", "  1777822918410__003.png", "promoted 1777822918326__001.png -> live/spaces/top_space_a", "  top_space_a  (7/19)", "spaces:top_space_b  (n=3)", "draw spaces/top_space_b (160x180, n=3, mode=txt2img, provider=openai)", "  1777822996799__001.png", "  1777822996842__002.png", "  1777822996881__003.png", "promoted 1777822996799__001.png -> live/spaces/top_space_b", "  top_space_b  (8/19)", "spaces:top_space_c  (n=3)", "draw spaces/top_space_c (160x180, n=3, mode=txt2img, provider=openai)", "  1777823071436__001.png", "  1777823071475__002.png", "  1777823071513__003.png", "promoted 1777823071436__001.png -> live/spaces/top_space_c", "  top_space_c  (9/19)", "spaces:bottom_banner_a  (n=3)", "draw spaces/bottom_banner_a (160x180, n=3, mode=txt2img, provider=openai)", "  1777823149016__001.png", "  1777823149059__002.png", "  1777823149108__003.png", "promoted 1777823149016__001.png -> live/spaces/bottom_banner_a", "  bottom_banner_a  (10/19)", "spaces:bottom_banner_b  (n=3)", "draw spaces/bottom_banner_b (160x180, n=3, mode=txt2img, provider=openai)", "  1777823226221__001.png", "  1777823226260__002.png", "  1777823226299__003.png", "promoted 1777823226221__001.png -> live/spaces/bottom_banner_b", "  bottom_banner_b  (11/19)", "spaces:bottom_space_a  (n=3)", "draw spaces/bottom_space_a (160x180, n=3, mode=txt2img, provider=openai)", "  1777823302497__001.png", "  1777823302536__002.png", "  1777823302576__003.png", "promoted 1777823302497__001.png -> live/spaces/bottom_space_a", "  bottom_space_a  (12/19)", "spaces:bottom_space_b  (n=3)", "draw spaces/bottom_space_b (160x180, n=3, mode=txt2img, provider=openai)", "  1777823379347__001.png", "  1777823379386__002.png", "  1777823379426__003.png", "promoted 1777823379347__001.png -> live/spaces/bottom_space_b", "  bottom_space_b  (13/19)", "spaces:bottom_space_c  (n=3)", "draw spaces/bottom_space_c (160x180, n=3, mode=txt2img, provider=openai)", "  1777823456828__001.png", "  1777823456867__002.png", "  1777823456904__003.png", "promoted 1777823456828__001.png -> live/spaces/bottom_space_c", "  bottom_space_c  (14/19)", "spaces:bottom_space_d  (n=3)", "draw spaces/bottom_space_d (160x180, n=3, mode=txt2img, provider=openai)", "FAIL spaces/bottom_space_d: The read operation timed out", "  bottom_space_d  (15/19)", "spaces:bottom_battle  (n=3)", "draw spaces/bottom_battle (160x180, n=3, mode=txt2img, provider=openai)", "  1777823951501__001.png", "  1777823951538__002.png", "  1777823951576__003.png", "promoted 1777823951501__001.png -> live/spaces/bottom_battle", "  bottom_battle  (16/19)", "spaces:side_property  (n=3)", "draw spaces/side_property (180x144, n=3, mode=txt2img, provider=openai)", "  1777824043927__001.png", "  1777824043966__002.png", "  1777824044006__003.png", "promoted 1777824043927__001.png -> live/spaces/side_property", "  side_property  (17/19)", "spaces:side_battle  (n=3)", "draw spaces/side_battle (180x144, n=3, mode=txt2img, provider=openai)", "  1777824119773__001.png", "  1777824119822__002.png", "  1777824119862__003.png", "promoted 1777824119773__001.png -> live/spaces/side_battle", "  side_battle  (18/19)", "spaces:top_battle  (n=3)", "draw spaces/top_battle (160x180, n=3, mode=txt2img, provider=openai)", "  1777824202671__001.png", "  1777824202710__002.png", "  1777824202750__003.png", "promoted 1777824202671__001.png -> live/spaces/top_battle", "  top_battle  (19/19)"]
14456df4842d	Analyze mockup with GPT-4o	analyze	demo-board	killed	0	\N	0.08	0	1777823160.004774	1777824202.7731178	\N	["\\u2190 cancel requested by user", "\\u2190 cancel requested by user", "\\u2190 cancel requested by user"]
0e806cdee28d	Composite preview	preview	demo-board	done	1	\N	0	0	1777845463.9139972	1777845464.5301208	\N	["compositing tiles  (0/48)", "  corner_tl@top_row.0  (1/48)", "  corner_tr@top_row.11  (2/48)", "  corner_bl@bottom_row.0  (3/48)", "  corner_br@bottom_row.11  (4/48)", "  top_banner_a@top_row.5  (5/48)", "  top_banner_b@top_row.7  (6/48)", "  top_space_a@top_row.1  (7/48)", "  top_space_a@top_row.4  (8/48)", "  top_space_a@top_row.8  (9/48)", "  top_space_b@top_row.2  (10/48)", "  top_space_b@top_row.6  (11/48)", "  top_space_b@top_row.9  (12/48)", "  top_space_c@top_row.3  (13/48)", "  top_space_c@top_row.10  (14/48)", "  bottom_banner_a@bottom_row.5  (15/48)", "  bottom_banner_b@bottom_row.6  (16/48)", "  bottom_space_a@bottom_row.1  (17/48)", "  bottom_space_a@bottom_row.4  (18/48)", "  bottom_space_b@bottom_row.2  (19/48)", "  bottom_space_b@bottom_row.10  (20/48)", "  bottom_space_c@bottom_row.3  (21/48)", "  bottom_space_c@bottom_row.8  (22/48)", "  bottom_space_d@bottom_row.9  (23/48)", "  bottom_battle@bottom_row.7  (24/48)", "  side_property@left_col.0  (25/48)", "  side_property@left_col.1  (26/48)", "  side_property@left_col.3  (27/48)", "  side_property@left_col.4  (28/48)", "  side_property@right_col.1  (29/48)", "  side_property@right_col.2  (30/48)", "  side_property@right_col.3  (31/48)", "  side_battle@left_col.2  (32/48)", "  side_battle@right_col.0  (33/48)", "  side_battle@right_col.4  (34/48)", "  top_battle@top_row.3  (35/48)", "  panel:panel_left_top  (36/48)", "  panel:panel_left_mid  (37/48)", "  panel:panel_left_bot  (38/48)", "  panel:panel_cleft_top  (39/48)", "  panel:panel_cleft_mid  (40/48)", "  panel:panel_cleft_bot  (41/48)", "  panel:panel_cright_top  (42/48)", "  panel:panel_cright_mid  (43/48)", "  panel:panel_cright_bot  (44/48)", "  panel:panel_right_top  (45/48)", "  panel:panel_right_mid  (46/48)", "  panel:panel_right_bot  (47/48)", "  centerpiece  (48/48)", "idle    -> /repo/data/boards/untitled-board-mopxc3av/workspace/preview/board_idle.png", "active  -> /repo/data/boards/untitled-board-mopxc3av/workspace/preview/board_active.png"]
3d6890cebb5d	Analyze mockup with GPT-4o	analyze	untitled-board-momdx7f5	done	1	\N	0.08	0.08	1777869545.3756335	1777869553.765508	\N	["analyze mockup with GPT-4o vision  (0/4)", "loading mockup: /repo/data/boards/untitled-board-momdx7f5/mockup/board.png", "  mockup loaded  (1/4)", "prompt: 3259 chars, 19 designs, 12 panels", "  image encoded  (2/4)", "\\u2192 calling GPT-4o vision (this takes ~10-20s)\\u2026", "  vision response received  (3/4)", "\\u2190 2144 chars received", "  done  (4/4)", "filled 33 / 33 prompt fields", "wrote 33 prompts to catalog  (spent ~$0.08 estimated)"]
\.


--
-- Data for Name: owned_boards; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.owned_boards (board_uuid, user_id, path_slug, created_ms, list_order) FROM stdin;
748e880d-ceab-46e3-96f8-7684903a2727	46c004b7a2a9482398aa262d103cf96e	damnation	1777682102780	0
ed1456f7-12ef-48d3-ac59-4c93634c8a33	46c004b7a2a9482398aa262d103cf96e	fantasy-quest	1777682102782	0
e92c3dc7-ec23-4f36-9f78-ee04abf6106b	46c004b7a2a9482398aa262d103cf96e	untitled-board-mokzf8v7	1777682102783	0
3de2757b-bbe2-4f74-9e36-d2e7d3285b48	46c004b7a2a9482398aa262d103cf96e	untitled-board-mom4pk3y	1777682102786	0
02ad5018-b82e-49ce-ad23-43d20ff06c9d	46c004b7a2a9482398aa262d103cf96e	untitled-board-mom9qwhn	1777682102787	0
ef5082cd-a41e-4319-9b9d-1f42842a518c	46c004b7a2a9482398aa262d103cf96e	untitled-board-momdx7f5	1777682102788	0
2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	46c004b7a2a9482398aa262d103cf96e	demo-board	1777822032099	0
\.


--
-- Data for Name: user_secrets; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.user_secrets (id, user_id, kind, ciphertext) FROM stdin;
1	46c004b7a2a9482398aa262d103cf96e	openai_api_key	gAAAAABp9Vxs0EWrlVtdY24lHSHYNQ8x3hYDhob9hIWal447kpncDutt1L4M9unBuZmaI8A6XppxGnuapW1vOtDDw_CS3xlrOBSw_QuLVcRvNzkF42w0qmzHk6KihRYA7ka1jp5YJlg3s02UwRuceqHWRBOU58sxoPySH49XUb1i6sgSNcplO0feugHaGE_goHd2XoGRG9jLSqyK_jNGk8Xnjxc_CigS882bwHxIJQQuCu_nWd5UER8OwoiWJ399xLvYMMi7L7T4MPH7QpMWSVnwCV36BVdRtWkHd_8d0vVggG2Nnsp_3o0=
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.users (id, email, password_hash, display_name, icon_glyph, icon_color, created_ms, last_login_ms, username) FROM stdin;
46c004b7a2a9482398aa262d103cf96e	admin@admin.com	$2b$12$heJK13dCZiAd838HM8DsL.XHvM0elqeVGuZwmafq7A6lvQEZ7jgOW	ben	✧	#902de1	1777514766934	1777822775314	admin
\.


--
-- Name: asset_versions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.asset_versions_id_seq', 1, false);


--
-- Name: cost_entries_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.cost_entries_id_seq', 80, true);


--
-- Name: user_secrets_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.user_secrets_id_seq', 1, true);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: asset_versions asset_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_versions
    ADD CONSTRAINT asset_versions_pkey PRIMARY KEY (id);


--
-- Name: board_games board_games_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.board_games
    ADD CONSTRAINT board_games_pkey PRIMARY KEY (id);


--
-- Name: browser_sessions browser_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.browser_sessions
    ADD CONSTRAINT browser_sessions_pkey PRIMARY KEY (sid);


--
-- Name: cost_entries cost_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cost_entries
    ADD CONSTRAINT cost_entries_pkey PRIMARY KEY (id);


--
-- Name: job_runs job_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_runs
    ADD CONSTRAINT job_runs_pkey PRIMARY KEY (id);


--
-- Name: owned_boards owned_boards_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owned_boards
    ADD CONSTRAINT owned_boards_pkey PRIMARY KEY (board_uuid);


--
-- Name: owned_boards owned_boards_user_id_path_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owned_boards
    ADD CONSTRAINT owned_boards_user_id_path_slug_key UNIQUE (user_id, path_slug);


--
-- Name: users uq_users_username; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_username UNIQUE (username);


--
-- Name: user_secrets user_secrets_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_secrets
    ADD CONSTRAINT user_secrets_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_asset_versions_board_cell; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_asset_versions_board_cell ON public.asset_versions USING btree (board_uuid, category, asset_id);


--
-- Name: ix_asset_versions_board_relpath; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_asset_versions_board_relpath ON public.asset_versions USING btree (board_uuid, rel_path);


--
-- Name: ix_browser_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_browser_sessions_user_id ON public.browser_sessions USING btree (user_id);


--
-- Name: ix_cost_entries_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cost_entries_ts ON public.cost_entries USING btree (ts);


--
-- Name: ix_job_runs_ended_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_job_runs_ended_at ON public.job_runs USING btree (ended_at);


--
-- Name: ix_owned_boards_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_owned_boards_user_id ON public.owned_boards USING btree (user_id);


--
-- Name: ix_user_secrets_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_secrets_user_id ON public.user_secrets USING btree (user_id);


--
-- Name: ix_user_secrets_user_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_user_secrets_user_kind ON public.user_secrets USING btree (user_id, kind);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: asset_versions asset_versions_board_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_versions
    ADD CONSTRAINT asset_versions_board_uuid_fkey FOREIGN KEY (board_uuid) REFERENCES public.board_games(id) ON DELETE CASCADE;


--
-- Name: browser_sessions browser_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.browser_sessions
    ADD CONSTRAINT browser_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: owned_boards owned_boards_board_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owned_boards
    ADD CONSTRAINT owned_boards_board_uuid_fkey FOREIGN KEY (board_uuid) REFERENCES public.board_games(id) ON DELETE CASCADE;


--
-- Name: owned_boards owned_boards_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.owned_boards
    ADD CONSTRAINT owned_boards_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_secrets user_secrets_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_secrets
    ADD CONSTRAINT user_secrets_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict WqFa4aZV8HUU96WFpa0bfJJektEGdEeT6ebNmQzL0nDUTCmqV5CaxkllibcrObH

