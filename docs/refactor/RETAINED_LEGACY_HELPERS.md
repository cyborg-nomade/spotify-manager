# Explicit legacy helper bindings retained in Item 7a

This is a source inventory of explicit function imports in shared operations,
bootstrap and infrastructure. A name can also be a compatibility export; its
presence does not imply that every operation invokes it. Types and constants
are omitted. Normal execution no longer locates functions through mutable
routine/processor module globals, and execution facades are prohibited by
`tests/bootstrap/test_direct_dependencies.py`.

The contract and decision for these bindings are:

| Contract | Justification | Decision |
| --- | --- | --- |
| Concrete Spotify/Last.fm/Random.org/Every Noise reads and accepted writes | Preserve raw expressions, source paths, payload validation, batching, retry and cancellation boundaries in the frozen SDK inventory. | Retain original source leaves in this item; evaluate replacements with equivalent ordered-call coverage in async Items 8–9. |
| Original file and state formats | Preserve bytes, timestamps, fallback decoding, audit schema, preview semantics and namespace validation. These helpers perform actual reads/writes or validation. | Keep those format implementations and supported imports; bind their actual owner explicitly. |
| Input parsing, record conversion and interaction adaptation | Preserve native validation errors, normalization, policy inputs and original choice-token meaning. | Retain cohesive validation/conversion helpers; primary workflow forwarding belongs only at public compatibility entries. |
| Original clock/configuration/default observations | Preserve original observation timing and live settings rather than introducing eager startup reads. | Retain until a scoped lifetime change has its own behavior evidence. |

Bootstrap constructors and application workflows are not in this list: they
have their own direct owners. Primary routine/processor execution facades remain
callable for external compatibility but are excluded from default dependency
bindings. Helpers can still call cohesive application parsing/catalog services
when they add their concrete IO, validation or conversion responsibility.

## Named bindings by original source

All module names below are relative to `spotify_manager`. Each list is
searchable by exact function name and uses the contracts/decisions above.

### `processors.control_file_processors`

- `_contains`
- `enrich_album`

### `processors.library_lookups`

- `_album_search`
- `_artist_search_items`
- `_direct_album`
- `_direct_artist_identity`
- `_fetch_album_tracks`
- `_liked_artist_statuses`
- `_live_artist_release_ids`
- `_live_liked_statuses`
- `_live_primary_track_ids`
- `_saved_artist_statuses`

### `processors.scrobble_lookups`

- `_direct_track`
- `_track_search`

### `processors.total_albums_processor`

- `_append_batch`
- `_append_single`
- `_create_playlist`
- `_next_album_page`
- `_next_track_page`
- `_recover_page`
- `_saved_page`
- `_track_page`

### `processors.your_library_processors`

- `is_in_library_artist`
- `is_in_library_track`
- `save_to_library_artist`
- `save_to_library_track`

### `routines.analyse_library`

- `_following_artists`
- `_initial_offset_reader`
- `_reconcile_artist_page`
- `_reconcile_offset_reader`
- `fetch_followed_artists_page`

### `routines.blast_from_past`

- `add_spotify_matches`
- `check_cancel`
- `eligible_dates`
- `fetch_random_indexes`
- `fetch_random_timestamp`
- `friday_track_cutoff`
- `liked_spotify_track_ids`
- `load_playlist_state`
- `load_scrobble_export`
- `load_scrobbles_by_date`
- `parse_playlist_id`
- `search_spotify_matches`
- `select_scrobble`

### `routines.blast_from_past_artists`

- `_catalog_tracks`
- `_liked_statuses`
- `_spotify_artist`
- `_track_popularities`
- `dormant_artists`

### `routines.composer_playlists`

- `load_owned_playlists`

### `routines.convert_library_file`

- `_analyse_added`
- `_analyse_removed`
- `_contains_added`
- `_contains_removed`

### `routines.daily_mind_radio`

- `anniversary_dates`

### `routines.discography`

- `_append_log`
- `_default_state`
- `_release_page`
- `_remove_batch`
- `_saved_batch`
- `_state_access`
- `format_release_indexes`
- `parse_playlist_id`
- `parse_playlist_ids`
- `parse_release_indexes`
- `validate_state`

### `routines.found_art`

- `parse_found_art_playlist_id`
- `validate_lastfm_configuration`

### `routines.genre_reveal`

- `_append_source_tracks`
- `_default_state`
- `_save_source_playlist`
- `append_genre_reveal_log`
- `first_incomplete_genre`
- `load_genre_playlist_source`
- `load_genre_reveal_state`
- `mark_genre_completed`
- `parse_destination_playlist_id`
- `read_public_page`
- `validate_state`

### `routines.new_kids`

- `_append_queue_track`
- `_append_review_track`
- `_artist_followed`
- `_assessment_liked`
- `_assessment_saved`
- `_assessment_top_liked`
- `_catalog_track_popularities`
- `_create_great_playlist`
- `_current_user_id`
- `_default_state`
- `_direct_call`
- `_playlist_artist_ids`
- `_release_saved`
- `_remove_queue_track`
- `_remove_release`
- `_remove_review_track`
- `_save_release`
- `_state_access`
- `_sync_local_album`
- `_unfollow_artist`
- `_utc_now`
- `append_event`
- `load_ranked_catalog`
- `load_release_tracks`
- `load_top_track_data`
- `parse_playlist_id`
- `remove_local_artist`
- `validate_state`

### `routines.new_wine`

- `_add_local_album`
- `_add_playlist_track`
- `_affinity_album_statuses`
- `_affinity_track_statuses`
- `_artist_key`
- `_clock`
- `_default_state`
- `_load_no_discovery_inventory`
- `_local_year`
- `_playlist_track_from_record`
- `_remove_local_album`
- `_remove_playlist_track`
- `_save_album`
- `_saved_for_drop`
- `_saved_for_keep`
- `_state_access`
- `_unsave_album`
- `append_cellar_log`
- `append_log`
- `current_year_releases`
- `get_liked_statuses`
- `load_playlist_tracks`
- `load_release_tracks`
- `parse_playlist_id`
- `validate_state`

### `routines.new_year`

- `_create_chart`
- `_move_position`
- `_post_pending`
- `_primary_artist`
- `_replace_chart`
- `validate_state`

### `routines.palace_of_memory`

- `_append_first_tracks`
- `_append_log`
- `_append_refresh_log`
- `_cursor_index`
- `_cursor_payload`
- `_default_state`
- `_direct_retry`
- `_read_palace_playlist`
- `_read_saved_album_page`
- `_replace_saved_albums`
- `_state_access`
- `load_first_track`
- `load_saved_albums`
- `palace_cutoff`
- `parse_playlist_id`
- `resolve_alphabetical_start`
- `search_spotify_album`
- `validate_state`

### `routines.queue_3`

- `_add_playlist_tracks`
- `_default_state`
- `_remove_playlist_uris`
- `_state_access`
- `append_event`
- `find_yearly_great_discoveries`
- `load_owned_playlists`
- `parse_playlist_id`
- `validate_state`

### `routines.recover_removed_albums`

- `_artist_statuses`
- `_clock`
- `_default_state`
- `_deserialize_state`
- `_fetch_album_metadata`
- `_follow_missing_artists`
- `_restore_album`
- `_saved_album`
- `_serialize_state`
- `_state_access`
- `_today`
- `add_album_to_local_files`
- `add_artists_to_local_files`
- `append_recovery_events`
- `load_removed_album_records`
- `spotify_album_artists`
- `validate_state`

### `routines.release_check`

- `_active_artists`
- `_add_to_playlist`
- `_deduplicate_wine_cellar`
- `_default_state`
- `_direct_retry`
- `_mapped_artist`
- `_pending_single`
- `_persist_state`
- `_playlist_membership`
- `_playlist_snapshot`
- `_run_id`
- `_state_access`
- `append_event`
- `load_recent_catalog`
- `load_release_tracks`
- `rank_lastfm_artists`
- `release_tags`
- `save_state`
- `search_spotify_artists`
- `state_fingerprint`
- `state_updated_at`
- `validate_state`

### `routines.requeue_for_a_dream`

- `_add_track`
- `_append_log`
- `_clock`
- `_direct_retry`
- `_remove_track`
- `parse_playlist_id`

### `routines.review_album_limits`

- `_follow_artist`
- `_is_artist_followed`
- `_state_access`
- `append_removed_album_log`
- `get_live_liked_track_count`
- `has_persisted_keep_decision`
- `known_artist_ids_by_name`
- `record_followed_artist`
- `record_review_decision`
- `remove_album_from_library`
- `resolve_album_artist`
- `validate_review_decisions`

### `routines.review_artists`

- `_default_state`
- `_deserialize_state`
- `_read_discography_page`
- `_read_first`
- `_read_ranked_page`
- `_read_tracks`
- `_serialize_state`
- `_state_access`
- `add_playlist_item`
- `append_events`
- `event`
- `load_cache`
- `load_models`
- `new_run_id`
- `playlist_membership`
- `remove_library_artists`
- `remove_playlist_items`
- `save_artists`
- `save_cache`
- `update_stats_after_unfollow`
- `validate_state`

### `routines.sauvignon`

- `_append_recommendation_albums`
- `load_first_track`
- `search_candidate_albums`

### `routines.scrobble_history`

- `_api_record`
- `_append_log`
- `_backup_export`
- `_load_export`
- `_load_legacy_delta`
- `_mark_export_checked`
- `_write_export_atomic`
- `check_cancel`

### `routines.slow_listening`

- `_add_playlist_track`
- `_clock`
- `_default_state`
- `_load_candidates`
- `_load_saved_statuses`
- `_remove_playlist_track`
- `_state_access`
- `append_log`
- `load_discography`
- `load_release_tracks`
- `parse_playlist_id`
- `validate_state`

### `routines.something_old`

- `_add_tracks`
- `_append_log`
- `_direct_retry`
- `_load_playlist_state`
- `_read_golden_artist_choice`
- `parse_playlist_id`
- `rank_golden_oldies`
- `resolve_spotify_artist`
- `select_album_tracks`
- `select_lastfm_top_tracks`
- `select_spotify_top_tracks`

### `routines.the_queue`

- `_cached_similar_artists`
- `_catalog_track_from_record`
- `_default_state`
- `_fill_follow`
- `_fill_following`
- `_flush_following`
- `_flush_result`
- `_liked_statuses`
- `_load_cache`
- `_mapped_artist`
- `_mapping_choice_reader`
- `_new_flush_run`
- `_persist_followed_artist`
- `_playlist_artist_ids`
- `_playlist_track_from_record`
- `_save_cache`
- `_state_access`
- `append_event`
- `previously_added_artist_keys`
- `validate_state`

### `routines.upload_library_files`

- `_build_lastfm_parts`
- `_load_and_validate_export`
- `materialize_lastfm_parts`
