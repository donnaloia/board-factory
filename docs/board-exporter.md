# Board project exporter

Builds a portable game-engine bundle: `project.json` plus copied assets under `assets/`.

**Code:** `app/domains/boards/exporter/` (geometry → interaction graph → asset/animation wiring → polish → write JSON).

**Download:** **Export Project** on a board — `GET …/export/project-bundle.zip` (`domains/boards/routes_api.py`).

## Illustrative `project.json` (abbreviated)

Real exports include every space, `export_manifest`, and optional `consumer_hints`.

```json
{
  "export_schema_version": "0.1.0-draft",
  "bundle_assets_root": "assets",
  "game_engine_instructions": "…handoff prose from exporter polish stage…",
  "board": { "canvas_pixels": [1920, 1080], "coordinate_space": "canvas_pixels_top_left" },
  "spaces": [
    {
      "id": "space__top_battle__top_row_3",
      "role": "perimeter",
      "catalog_ref": { "kind": "board_space_design", "design_id": "top_battle", "position_ref": "top_row.3" },
      "rect_canvas": { "x": 480, "y": 0, "width": 160, "height": 180 },
      "assets": { "still": "assets/spaces/top_battle/live.png", "animation": null }
    },
    {
      "id": "space_panel_panel_right_mid",
      "role": "functional",
      "catalog_ref": { "kind": "feature_panel", "panel_id": "panel_right_mid" },
      "assets": {
        "still": "assets/spaces/panel_right_mid/live.png",
        "animation": {
          "path": "assets/spaces/panel_right_mid/animation_live.apng",
          "encoding": "apng",
          "fps": 30,
          "animation_prompt": "…from committed proposal manifest…"
        }
      }
    }
  ],
  "interaction_graph": [
    {
      "id": "edge_land__top_battle__panel_right_mid",
      "from_space_id": "space__top_battle__top_row_3",
      "from_space_ids": ["space__top_battle__top_row_3", "space__top_battle__top_row_10"],
      "trigger_space_design_id": "top_battle",
      "to_space_id": "space_panel_panel_right_mid",
      "target_panel_id": "panel_right_mid",
      "link_kind": "hidden_ui_route",
      "trigger": {
        "event": "land",
        "actions": [{
          "type": "play_space_animation",
          "target_space_id": "space_panel_panel_right_mid",
          "target_panel_id": "panel_right_mid",
          "only_if_asset_present": true
        }]
      }
    }
  ]
}
```

Land edges list **all** perimeter tile ids for the linked design (`from_space_ids`). Match on land when the token’s space id is in that list, or when `catalog_ref.design_id` equals `trigger_space_design_id`.
