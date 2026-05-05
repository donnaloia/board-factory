--
-- PostgreSQL database dump
--

\restrict xvrjOOxc8L1Wj8vax7eaC3cr4E68LqhWRZsrFizfeM9SqJZ57gLOK7OcgsXSVz8

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
ALTER TABLE IF EXISTS ONLY public.cells DROP CONSTRAINT IF EXISTS cells_board_uuid_fkey;
ALTER TABLE IF EXISTS ONLY public.browser_sessions DROP CONSTRAINT IF EXISTS browser_sessions_user_id_fkey;
ALTER TABLE IF EXISTS ONLY public.asset_versions DROP CONSTRAINT IF EXISTS asset_versions_cell_id_fkey;
ALTER TABLE IF EXISTS ONLY public.asset_versions DROP CONSTRAINT IF EXISTS asset_versions_board_uuid_fkey;
DROP INDEX IF EXISTS public.ix_users_email;
DROP INDEX IF EXISTS public.ix_user_secrets_user_kind;
DROP INDEX IF EXISTS public.ix_user_secrets_user_id;
DROP INDEX IF EXISTS public.ix_owned_boards_user_id;
DROP INDEX IF EXISTS public.ix_job_runs_ended_at;
DROP INDEX IF EXISTS public.ix_cost_entries_ts;
DROP INDEX IF EXISTS public.ix_cells_board_kind;
DROP INDEX IF EXISTS public.ix_browser_sessions_user_id;
DROP INDEX IF EXISTS public.ix_asset_versions_cell_id;
DROP INDEX IF EXISTS public.ix_asset_versions_board_relpath;
DROP INDEX IF EXISTS public.ix_asset_versions_board_cell;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS users_pkey;
ALTER TABLE IF EXISTS ONLY public.user_secrets DROP CONSTRAINT IF EXISTS user_secrets_pkey;
ALTER TABLE IF EXISTS ONLY public.users DROP CONSTRAINT IF EXISTS uq_users_username;
ALTER TABLE IF EXISTS ONLY public.cells DROP CONSTRAINT IF EXISTS uq_cells_board_kind_slug;
ALTER TABLE IF EXISTS ONLY public.owned_boards DROP CONSTRAINT IF EXISTS owned_boards_user_id_path_slug_key;
ALTER TABLE IF EXISTS ONLY public.owned_boards DROP CONSTRAINT IF EXISTS owned_boards_pkey;
ALTER TABLE IF EXISTS ONLY public.job_runs DROP CONSTRAINT IF EXISTS job_runs_pkey;
ALTER TABLE IF EXISTS ONLY public.cost_entries DROP CONSTRAINT IF EXISTS cost_entries_pkey;
ALTER TABLE IF EXISTS ONLY public.cells DROP CONSTRAINT IF EXISTS cells_pkey;
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
DROP TABLE IF EXISTS public.cells;
DROP TABLE IF EXISTS public.browser_sessions;
DROP TABLE IF EXISTS public.board_games;
DROP SEQUENCE IF EXISTS public.asset_versions_id_seq;
DROP TABLE IF EXISTS public.asset_versions;
DROP TABLE IF EXISTS public.alembic_version;
DROP EXTENSION IF EXISTS pgcrypto;
--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


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
    meta_json text,
    cell_id uuid NOT NULL
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
    body_json jsonb NOT NULL,
    updated_ms bigint NOT NULL,
    palette_json text,
    palette_gpl_text text,
    style_lock_updated_ms bigint,
    project character varying(512) DEFAULT ''::character varying NOT NULL,
    board_size_w integer DEFAULT 0 NOT NULL,
    board_size_h integer DEFAULT 0 NOT NULL,
    palette_size integer DEFAULT 36 NOT NULL,
    provider character varying(32) DEFAULT 'openai'::character varying NOT NULL,
    openai_model character varying(64) DEFAULT 'gpt-image-2'::character varying NOT NULL,
    openai_quality character varying(16) DEFAULT 'low'::character varying NOT NULL,
    pixellab_model character varying(64) DEFAULT 'pixflux_sharp'::character varying NOT NULL,
    generation_configured boolean DEFAULT false NOT NULL,
    frame_enabled boolean DEFAULT false NOT NULL,
    frame_apply_to_panels boolean DEFAULT true NOT NULL,
    frame_apply_to_spaces boolean DEFAULT false NOT NULL,
    style_reference_image character varying(1024) DEFAULT ''::character varying NOT NULL,
    style_prompt text DEFAULT ''::text NOT NULL
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
-- Name: cells; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cells (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    board_uuid character varying(36) NOT NULL,
    kind character varying(16) NOT NULL,
    slug character varying(128) NOT NULL,
    position_index integer NOT NULL,
    prompt text DEFAULT ''::text NOT NULL,
    needs_active boolean DEFAULT false NOT NULL,
    active_kind character varying(16) DEFAULT 'none'::character varying NOT NULL,
    space_kind character varying(16),
    positions_json jsonb,
    bbox_x1 integer,
    bbox_y1 integer,
    bbox_x2 integer,
    bbox_y2 integer,
    target_w integer,
    target_h integer,
    CONSTRAINT ck_cells_active_kind_enum CHECK (((active_kind)::text = ANY ((ARRAY['glow'::character varying, 'pulse'::character varying, 'flicker'::character varying, 'none'::character varying])::text[]))),
    CONSTRAINT ck_cells_kind_enum CHECK (((kind)::text = ANY ((ARRAY['space'::character varying, 'panel'::character varying, 'centerpiece'::character varying])::text[]))),
    CONSTRAINT ck_cells_shape_by_kind CHECK (((((kind)::text = 'space'::text) AND (space_kind IS NOT NULL) AND (positions_json IS NOT NULL) AND (bbox_x1 IS NULL) AND (bbox_y1 IS NULL) AND (bbox_x2 IS NULL) AND (bbox_y2 IS NULL) AND (target_w IS NULL) AND (target_h IS NULL)) OR (((kind)::text = ANY ((ARRAY['panel'::character varying, 'centerpiece'::character varying])::text[])) AND (space_kind IS NULL) AND (positions_json IS NULL) AND (bbox_x1 IS NOT NULL) AND (bbox_y1 IS NOT NULL) AND (bbox_x2 IS NOT NULL) AND (bbox_y2 IS NOT NULL) AND (target_w IS NOT NULL) AND (target_h IS NOT NULL)))),
    CONSTRAINT ck_cells_space_kind_enum CHECK (((space_kind IS NULL) OR ((space_kind)::text = ANY ((ARRAY['standard'::character varying, 'event'::character varying])::text[]))))
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
0019_promote_cells_table
\.


--
-- Data for Name: asset_versions; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.asset_versions (id, board_uuid, category, asset_id, basename, rel_path, sha256, ts_ms, meta_json, cell_id) FROM stdin;
1	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	centerpiece	centerpiece	1777824354302__001.png	history/centerpiece/centerpiece/1777824354302__001.png	22ba7e59588736439f2953d3844937877b0c8845063f7e863deb4e20c461573a	1777931988688	\N	89bf51b5-9e65-4488-986f-6332e0e40f11
2	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	centerpiece	centerpiece	1777824354770__002.png	history/centerpiece/centerpiece/1777824354770__002.png	9cc29b03de4d498e17c18cec162cf61441ec7a604a3225d7bbb9833534a9975f	1777931988691	\N	89bf51b5-9e65-4488-986f-6332e0e40f11
3	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	centerpiece	centerpiece	1777824355265__003.png	history/centerpiece/centerpiece/1777824355265__003.png	c898daa3878455d96a69601e702d968cbde3b466adb35e9fd1acc5168887da9c	1777931988694	\N	89bf51b5-9e65-4488-986f-6332e0e40f11
4	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	centerpiece	centerpiece	1777824355751__004.png	history/centerpiece/centerpiece/1777824355751__004.png	3f530a604a991af9cbf93744cb702bf952b79070d3dab122bec8db1acdb05bff	1777931988696	\N	89bf51b5-9e65-4488-986f-6332e0e40f11
5	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_bot	1777825789571__001.png	history/panels/panel_cleft_bot/1777825789571__001.png	3ea7771f7cfcc7dfab468165af503465e75115f9df6bab1a49fdb680b6007ee6	1777931988697	\N	7401a1e1-4a25-44e2-9f04-ed249ef0b08c
6	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_bot	1777825789635__002.png	history/panels/panel_cleft_bot/1777825789635__002.png	47e503b83280922a332d05df825841f8bc1fa5441cae63a0084a2878d18e374c	1777931988697	\N	7401a1e1-4a25-44e2-9f04-ed249ef0b08c
7	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_bot	1777825789702__003.png	history/panels/panel_cleft_bot/1777825789702__003.png	689514f13cf4bc9a663c4b91d0c793bcfbf46cde38963bdc9a0f506826da2ac7	1777931988698	\N	7401a1e1-4a25-44e2-9f04-ed249ef0b08c
8	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_bot	1777825789774__004.png	history/panels/panel_cleft_bot/1777825789774__004.png	3b1ad4ce369809519f5206fb70ee0cc120b9f5a119bd46d9fc9ed2cb45960834	1777931988698	\N	7401a1e1-4a25-44e2-9f04-ed249ef0b08c
9	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_mid	1777824276922__001.png	history/panels/panel_cleft_mid/1777824276922__001.png	f942d8ed0aa88b9d40e7e60859f1200e5a3950b4a82b101d06d2da2edc4c9881	1777931988699	\N	dde185fd-bc66-45ca-83f0-6b846e12c8b3
10	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_mid	1777824276996__002.png	history/panels/panel_cleft_mid/1777824276996__002.png	b73cf12c7facbab11daf7bfdee7c6056d5e2f99a912ca962339aa5402610b227	1777931988699	\N	dde185fd-bc66-45ca-83f0-6b846e12c8b3
11	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_mid	1777824277068__003.png	history/panels/panel_cleft_mid/1777824277068__003.png	14da4a0429701850fd91191a330c8771b72d0b8a5b29e1bf89dcd7c2a2e1df80	1777931988700	\N	dde185fd-bc66-45ca-83f0-6b846e12c8b3
12	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_mid	1777824277138__004.png	history/panels/panel_cleft_mid/1777824277138__004.png	6d9ef2506ac20666d8d56c57efc862c88201211b106c1448b54a2ba5b138baea	1777931988700	\N	dde185fd-bc66-45ca-83f0-6b846e12c8b3
13	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_mid	1777824887017__005.png	history/panels/panel_cleft_mid/1777824887017__005.png	bfc3cee345125ff30e154e3336fd6e5f12c2d2f238b9a01fd6633c3f77d34cda	1777931988701	\N	dde185fd-bc66-45ca-83f0-6b846e12c8b3
14	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_mid	1777824887089__006.png	history/panels/panel_cleft_mid/1777824887089__006.png	01b4884dbbbe5d9f7cd928f2eb02325dfefada79fbd9e560b73a6b4558aeee98	1777931988709	\N	dde185fd-bc66-45ca-83f0-6b846e12c8b3
15	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_mid	1777824887157__007.png	history/panels/panel_cleft_mid/1777824887157__007.png	df75b3d3e2a821ba4dab19c767fb841616a434602f8334e4f5573c5cafeecfcf	1777931988709	\N	dde185fd-bc66-45ca-83f0-6b846e12c8b3
16	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_mid	1777824887227__008.png	history/panels/panel_cleft_mid/1777824887227__008.png	7219781e4268cfeb7739f341cff93fd8282438664fd9d2bfa3222c987c54f06f	1777931988710	\N	dde185fd-bc66-45ca-83f0-6b846e12c8b3
17	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_top	1777825198276__001.png	history/panels/panel_cleft_top/1777825198276__001.png	9de5f134598f3c21f57420b3d437a4c407dadcaac2a40eef794f5aefe956b6d8	1777931988713	\N	ce43169f-64c2-45d6-952c-6358b5cee856
18	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_top	1777825198361__002.png	history/panels/panel_cleft_top/1777825198361__002.png	22c4cb08bf4bb6de639137a5d873dde30eec230ce77c097f6417f1be6792b71e	1777931988714	\N	ce43169f-64c2-45d6-952c-6358b5cee856
19	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_top	1777825198437__003.png	history/panels/panel_cleft_top/1777825198437__003.png	2414894b738a08e4b4e832b590b1ff487c48baa02df628859c78cf7bf45a10b2	1777931988718	\N	ce43169f-64c2-45d6-952c-6358b5cee856
20	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_top	1777825198514__004.png	history/panels/panel_cleft_top/1777825198514__004.png	4636cc21d1bab047ef7d8d3924e17e25e7b45a6171f6add49c75983070877df4	1777931988718	\N	ce43169f-64c2-45d6-952c-6358b5cee856
21	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_top	1777825372791__005.png	history/panels/panel_cleft_top/1777825372791__005.png	51670c444ed9dab4c25279a58b4e1bb74f0da753bb4bbfc46a1551cfd6df4d3f	1777931988719	\N	ce43169f-64c2-45d6-952c-6358b5cee856
22	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_top	1777825372864__006.png	history/panels/panel_cleft_top/1777825372864__006.png	f5ec7f5d6c586434a12f629924fa36d49445cc9ad6caefd26d8a0b6fb9e4bbee	1777931988722	\N	ce43169f-64c2-45d6-952c-6358b5cee856
23	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_top	1777825372940__007.png	history/panels/panel_cleft_top/1777825372940__007.png	6d0ffbc867f3ab9d90de98e43e56735d0dfe6dadb32ce8d777ec1abeae079143	1777931988723	\N	ce43169f-64c2-45d6-952c-6358b5cee856
24	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cleft_top	1777825373011__008.png	history/panels/panel_cleft_top/1777825373011__008.png	6fb78ba5abc30f76acf47d78206b8b1913c5080a14eaf752d446f44681821d59	1777931988723	\N	ce43169f-64c2-45d6-952c-6358b5cee856
25	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777825446773__001.png	history/panels/panel_cright_bot/1777825446773__001.png	029e46e8997122e82ed7b156f94485055da97cc1408474ad1893e882f739a60e	1777931988723	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
26	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777825447037__002.png	history/panels/panel_cright_bot/1777825447037__002.png	705bce6acd98b8d2eb07622c186e53ad07c4d29236a3cfabdfbcd1b8e7306b92	1777931988725	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
27	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777825447309__003.png	history/panels/panel_cright_bot/1777825447309__003.png	0cea417475153f808e3f46029c3081e2eeee3c5985d3c5767e47332bc45ad194	1777931988726	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
28	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777825447605__004.png	history/panels/panel_cright_bot/1777825447605__004.png	c994e862b17517e3eed4929194c21eee21335a62f870d3e5398c3422192f825c	1777931988727	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
29	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777825926619__005.png	history/panels/panel_cright_bot/1777825926619__005.png	5eb8d45f4cea7be3bece50627e6aaf7de9da617805132d9652b4ffe92517cb67	1777931988728	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
30	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777825926692__006.png	history/panels/panel_cright_bot/1777825926692__006.png	11ce050335d45418433e6b0bf71c58cb306ec00258370515c375c3506e93d73e	1777931988728	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
31	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777825926767__007.png	history/panels/panel_cright_bot/1777825926767__007.png	a7dc1056d95bfae14973498b2f64b30489a31b55a23dc07379bd91ebe06607ec	1777931988729	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
32	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777825926834__008.png	history/panels/panel_cright_bot/1777825926834__008.png	36c1768179a7a11c68cdc30dc8c92b4eb1f113b5194cac2aa54a90beaa61c4bb	1777931988730	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
33	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847316270__009.png	history/panels/panel_cright_bot/1777847316270__009.png	9b68132bed8ce952ca6cfbc6802e3c065916628dd3b636a15d28183fcff705d4	1777931988731	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
34	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847316341__010.png	history/panels/panel_cright_bot/1777847316341__010.png	e73958df062e6e8cc42fbb75a71fa7495858b96cb0105a849cc8ed4da255f7b9	1777931988731	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
35	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847316414__011.png	history/panels/panel_cright_bot/1777847316414__011.png	9ff3d18e66b49b83c429a07f85039371b6ba8818c0e6e452225c8fcde279b609	1777931988757	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
36	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847316488__012.png	history/panels/panel_cright_bot/1777847316488__012.png	b6444a612497abbdb07a14a13bdaab03bb4abac61ed426db521794fa4bd608b9	1777931988758	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
37	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847694869__013.png	history/panels/panel_cright_bot/1777847694869__013.png	ec598b56b8e44a9ceaf1a6310769c1d55aaef187762e94ffb6eb89348367f0e7	1777931988759	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
38	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847694949__014.png	history/panels/panel_cright_bot/1777847694949__014.png	9f19f917c3a5887a16fe7b523eedafc3c2890b1cc3649f91322d800665487f3d	1777931988759	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
39	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847695031__015.png	history/panels/panel_cright_bot/1777847695031__015.png	29fd9e819253ba6415b76a42ed60a6512bf4447f1122ecf01c16305444613560	1777931988760	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
40	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847695117__016.png	history/panels/panel_cright_bot/1777847695117__016.png	499dfb7943ef222308ce9964f1a79bf559a6a9c9189ed2a5d1cdae317e550dad	1777931988760	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
41	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847881430__017.png	history/panels/panel_cright_bot/1777847881430__017.png	d143d675a5575bef271d293246eb8586d5bfbef59ae77c1fe7309f2f83a834fe	1777931988761	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
42	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847881536__018.png	history/panels/panel_cright_bot/1777847881536__018.png	3bcf707add5bea90ccc1934c05edfef2f69b85a86bad35d6e0a993c098f2e9d0	1777931988761	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
43	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847881650__019.png	history/panels/panel_cright_bot/1777847881650__019.png	52384761fb573e6b13bd305c174ccbc3e856e7805379e52931ae180bb470adbe	1777931988762	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
44	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_bot	1777847881755__020.png	history/panels/panel_cright_bot/1777847881755__020.png	2b8fb3912d367c82f7bcb5b2ed366175d3e67436169c78ca51a95a72a61d24a5	1777931988762	\N	5f17228e-6a0b-494e-b633-281f40e5e39c
45	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_mid	1777824955642__001.png	history/panels/panel_cright_mid/1777824955642__001.png	748c266721688e3be5bac83bcb79218af92efe215d811a4edc4f73f7682d1d0c	1777931988764	\N	7aa5b745-48c6-440e-8b2a-c4c4f5d59443
46	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_mid	1777824955720__002.png	history/panels/panel_cright_mid/1777824955720__002.png	dddf7845ec4a8f6a7b36065b6da45807ab74ad52a8d718fde0cac85c0524eb23	1777931988764	\N	7aa5b745-48c6-440e-8b2a-c4c4f5d59443
47	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_mid	1777824955794__003.png	history/panels/panel_cright_mid/1777824955794__003.png	f06ebb13beb3d6f127a6cc110a4037d09c0b39a5293e81bdb0bdc42a008f1fc2	1777931988765	\N	7aa5b745-48c6-440e-8b2a-c4c4f5d59443
48	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_mid	1777824955874__004.png	history/panels/panel_cright_mid/1777824955874__004.png	e7c9b6eacc75863bfcd5608e3291d9323b0fad0f3177d1a065dd762d26ceb3d0	1777931988765	\N	7aa5b745-48c6-440e-8b2a-c4c4f5d59443
49	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_mid	1777847123061__005.png	history/panels/panel_cright_mid/1777847123061__005.png	f6f6c8feb26b29d0c58f4ad531000cbcce6039f548c3d300e298e8a800a5b52c	1777931988766	\N	7aa5b745-48c6-440e-8b2a-c4c4f5d59443
50	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_mid	1777847123133__006.png	history/panels/panel_cright_mid/1777847123133__006.png	e1bec0d65c0bb6d82910e06796358bdb37af85118f3ae68126ed34864744e74e	1777931988767	\N	7aa5b745-48c6-440e-8b2a-c4c4f5d59443
51	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_mid	1777847123209__007.png	history/panels/panel_cright_mid/1777847123209__007.png	f70747d3fbfb818b0f5261435fa92fa4fd4195c9e5bf8c9ccd8517f2be4d34bf	1777931988768	\N	7aa5b745-48c6-440e-8b2a-c4c4f5d59443
52	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_mid	1777847123280__008.png	history/panels/panel_cright_mid/1777847123280__008.png	188e57cece748333c6d372ba8cc506e9e52a532358448e371db61011660b28f4	1777931988768	\N	7aa5b745-48c6-440e-8b2a-c4c4f5d59443
53	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_top	1777826080212__001.png	history/panels/panel_cright_top/1777826080212__001.png	6cd9e71bc35a87423c1507e46c897e819224ccf455cc98d3666a6d09c51a1bca	1777931988768	\N	2888765c-8054-4a54-83c4-551eccb8a741
54	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_top	1777826080291__002.png	history/panels/panel_cright_top/1777826080291__002.png	d029542880f1fad8759ed8e863d1024384a592b056b30035c4305eae71653328	1777931988769	\N	2888765c-8054-4a54-83c4-551eccb8a741
55	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_top	1777826080365__003.png	history/panels/panel_cright_top/1777826080365__003.png	3d7579ff0a56102a62b786079282ae54da9989f8824f9127530f7f1c29eff374	1777931988769	\N	2888765c-8054-4a54-83c4-551eccb8a741
56	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_top	1777826080443__004.png	history/panels/panel_cright_top/1777826080443__004.png	9ea4fd5b0ee77a78d1dca842d94f10e8c60c79e3e95532fd44fc0408003a9f14	1777931988770	\N	2888765c-8054-4a54-83c4-551eccb8a741
57	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_top	1777826267429__005.png	history/panels/panel_cright_top/1777826267429__005.png	3dddbdfa07455caa0389bff92bdd87b4f9d04f68f02287e715ad53acab13e7e8	1777931988770	\N	2888765c-8054-4a54-83c4-551eccb8a741
58	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_top	1777826267798__006.png	history/panels/panel_cright_top/1777826267798__006.png	08c893e9adad5f76576ebf3d18843dab586114f4e42dd08969f52ecee8081e23	1777931988771	\N	2888765c-8054-4a54-83c4-551eccb8a741
59	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_top	1777826268133__007.png	history/panels/panel_cright_top/1777826268133__007.png	291ab3fa0ec4bb6667a1f833f4c21bea74aabd0f17eb1e21b8e90ee8a3172e27	1777931988771	\N	2888765c-8054-4a54-83c4-551eccb8a741
60	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_cright_top	1777826268483__008.png	history/panels/panel_cright_top/1777826268483__008.png	36d7ebe5378a020c5cbe998489baa61970add977bd5e9a6a6e77e27909ddfe9a	1777931988772	\N	2888765c-8054-4a54-83c4-551eccb8a741
61	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777825019345__001.png	history/panels/panel_left_bot/1777825019345__001.png	1c90c3f464fe4fc2751a2eb646c57df9a350d24dbd45b26ccfd8ea4a2f317ca0	1777931988772	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
62	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777825019421__002.png	history/panels/panel_left_bot/1777825019421__002.png	aa9e19016627bef0895d70f58e60b729d8d9051ec54f1d0e27df36faf31bf240	1777931988773	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
63	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777825019498__003.png	history/panels/panel_left_bot/1777825019498__003.png	b62a9217877ce3131e9fb6a3ac12c708263233d6833b8ffd2a40cfbf5d633fa8	1777931988773	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
64	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777825019571__004.png	history/panels/panel_left_bot/1777825019571__004.png	ac7c903728ab666e421b1575427bcfbb885ce55c379a1ee7e6568ce62719ae0b	1777931988773	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
65	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777844856775__005.png	history/panels/panel_left_bot/1777844856775__005.png	e75f8b2707450fbf30246d7ef79f2cd083019889b4cc09550ef335e9eb67449b	1777931988774	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
66	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777844857042__006.png	history/panels/panel_left_bot/1777844857042__006.png	f010d6d53738fee1bdf436f6369ba51a524a1590584a5a0529c8a2fb0c71d871	1777931988774	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
67	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777844857324__007.png	history/panels/panel_left_bot/1777844857324__007.png	0d76641a21cce7d03ce649535a440f8ac7db46fe635bc271c3b109961d0a4c3f	1777931988775	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
68	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777844857620__008.png	history/panels/panel_left_bot/1777844857620__008.png	b729930cfaff39727d9fb65bf7e4f4dfa61bb71458bc3fc4a7e822a6788f11a2	1777931988775	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
69	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777845103569__009.png	history/panels/panel_left_bot/1777845103569__009.png	f87a77ce7c2b0e4d1a7e3f37e05969ba73a3f9d94d28d87ca329c257293d45c1	1777931988776	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
70	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777845103644__010.png	history/panels/panel_left_bot/1777845103644__010.png	d0b45525a612b83c78b5ea20b5eb0d7aab2d91de0c2f0192fd336c26c5d4c5de	1777931988776	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
71	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777845103722__011.png	history/panels/panel_left_bot/1777845103722__011.png	3df4c75e82d37d34a40e9cc971b98e3b5f69ac2d757afb89dcce90fd1972f104	1777931988777	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
72	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_bot	1777845103803__012.png	history/panels/panel_left_bot/1777845103803__012.png	c3258e4e40041138cd9c29706e0e36357c8f49bcbd716524c63cc72463d802ee	1777931988777	\N	2de6df2f-d711-4994-a76e-6b0de1241c10
73	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_mid	1777826004367__001.png	history/panels/panel_left_mid/1777826004367__001.png	135191cb9bc6fd718f6311cce28cc2407b2b036a54471a839b8ae9a1958cc2e0	1777931988777	\N	67a2a34e-190d-4f02-a222-20e1505d18c2
74	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_mid	1777826004443__002.png	history/panels/panel_left_mid/1777826004443__002.png	77dd2712f03172fad2c02d65bbcf62c759320b4e87ad371144abe025a1516995	1777931988778	\N	67a2a34e-190d-4f02-a222-20e1505d18c2
75	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_mid	1777826004522__003.png	history/panels/panel_left_mid/1777826004522__003.png	f38cd67a3cb6b388305271cb38f927844f72ae1a3bea1a64139acec2ec36b06c	1777931988778	\N	67a2a34e-190d-4f02-a222-20e1505d18c2
76	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_mid	1777826004599__004.png	history/panels/panel_left_mid/1777826004599__004.png	07ee61579127e014c903a3473aae670ba794cfbe4aa31a6e8b6726e1b6890fba	1777931988778	\N	67a2a34e-190d-4f02-a222-20e1505d18c2
77	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_top	1777825587797__001.png	history/panels/panel_left_top/1777825587797__001.png	af3dc61d8d8adc00c4cc0d0fee3c2ffced904d558a5af5e580d07a1fbf64b25f	1777931988779	\N	460f79ce-307f-49a5-a4a5-1209579ead34
78	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_top	1777825587869__002.png	history/panels/panel_left_top/1777825587869__002.png	94eb7aa289d684c8a91f294a3d7f61b9473e394213d3ebf0e74cbe083f4ba7de	1777931988780	\N	460f79ce-307f-49a5-a4a5-1209579ead34
79	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_top	1777825587938__003.png	history/panels/panel_left_top/1777825587938__003.png	06dcad5857805409ede9c2502390dfdb5fa56c5d5f9674fbf4b9b77f92aba7be	1777931988780	\N	460f79ce-307f-49a5-a4a5-1209579ead34
80	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_top	1777825588006__004.png	history/panels/panel_left_top/1777825588006__004.png	0a37be82c66ba9edf68d71373bf49e017433a7416761a4478ae56f491442bc3c	1777931988780	\N	460f79ce-307f-49a5-a4a5-1209579ead34
81	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_top	1777825723853__005.png	history/panels/panel_left_top/1777825723853__005.png	ed96837395f0f396d91475858f5498d0d5d568c078f7665f296f7fb76957276e	1777931988781	\N	460f79ce-307f-49a5-a4a5-1209579ead34
82	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_top	1777825723930__006.png	history/panels/panel_left_top/1777825723930__006.png	f3ed494064e46c287a4953e15c326db2031603bf45d624d3e26ed02c33a1d2c2	1777931988782	\N	460f79ce-307f-49a5-a4a5-1209579ead34
83	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_top	1777825724002__007.png	history/panels/panel_left_top/1777825724002__007.png	9a4fa0a60060527c8a75b413541af0a972516a5f80711ef71296b724563839ed	1777931988782	\N	460f79ce-307f-49a5-a4a5-1209579ead34
84	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_left_top	1777825724075__008.png	history/panels/panel_left_top/1777825724075__008.png	71a5c43b67cc3e05b0bcb8f0e7419131b3d94ce052f5af97d65d0c6367287b93	1777931988783	\N	460f79ce-307f-49a5-a4a5-1209579ead34
85	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_bot	1777844484349__001.png	history/panels/panel_right_bot/1777844484349__001.png	5e21c5bc00d1e69ab452a8752f9d1e5e7a7c1c6e726f66270785fbd43a4404a2	1777931988784	\N	7631057a-746e-4aea-ac4d-c2744399a38b
86	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_bot	1777844484420__002.png	history/panels/panel_right_bot/1777844484420__002.png	eeb1b287fa73ee1226dbb6815361cb78b2428864d4513066521a066a1fc92673	1777931988785	\N	7631057a-746e-4aea-ac4d-c2744399a38b
87	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_bot	1777844484491__003.png	history/panels/panel_right_bot/1777844484491__003.png	45c04924bb9ae2ce5720015a2f3d4613e8c7b73a7cb4eb81db82928594e9ca81	1777931988785	\N	7631057a-746e-4aea-ac4d-c2744399a38b
88	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_bot	1777844484565__004.png	history/panels/panel_right_bot/1777844484565__004.png	dae164fdb488667e4b6b30461d78661073ca2520a660334a2a3f84888710ec31	1777931988786	\N	7631057a-746e-4aea-ac4d-c2744399a38b
89	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_bot	1777845234720__005.png	history/panels/panel_right_bot/1777845234720__005.png	773ae36fb8d5e104b9147adf898ddb51f149380313ef7d371a48dbbe0a669a57	1777931988786	\N	7631057a-746e-4aea-ac4d-c2744399a38b
90	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_bot	1777845234795__006.png	history/panels/panel_right_bot/1777845234795__006.png	971b285bbf19702ff087f9f93c65346fa735c786795ab8bb090c6b7b97613a8e	1777931988787	\N	7631057a-746e-4aea-ac4d-c2744399a38b
91	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_bot	1777845234867__007.png	history/panels/panel_right_bot/1777845234867__007.png	fb4147c1f0a68bb491e92eb11c728e2fc4c407b0ea564afebbb709c300204c78	1777931988788	\N	7631057a-746e-4aea-ac4d-c2744399a38b
92	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_bot	1777845234938__008.png	history/panels/panel_right_bot/1777845234938__008.png	db89136bcfd9c067f86638f9e803dd7d58813ba83c8a853443bb1ffeab35a5bf	1777931988789	\N	7631057a-746e-4aea-ac4d-c2744399a38b
93	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_mid	1777844385108__001.png	history/panels/panel_right_mid/1777844385108__001.png	696ee25bd397a97639b2d2450dca3e4bd2b356e87476fe839db2f681d19053c4	1777931988789	\N	1e0dc30f-c899-4c89-bd69-e95c31ff85b9
94	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_mid	1777844385179__002.png	history/panels/panel_right_mid/1777844385179__002.png	8b39937ebef6b1966f6799cc2b905de7141ae55040f5da5f34dd04ffe296049d	1777931988790	\N	1e0dc30f-c899-4c89-bd69-e95c31ff85b9
95	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_mid	1777844385372__003.png	history/panels/panel_right_mid/1777844385372__003.png	d0d3041689adddc18ca88e2e975b80a7eb192b3c6ee0f5d6a6515427dd3fe156	1777931988791	\N	1e0dc30f-c899-4c89-bd69-e95c31ff85b9
96	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_mid	1777844385448__004.png	history/panels/panel_right_mid/1777844385448__004.png	9dcc232f9757b97c2a6817eba662bc8daf60908a161afc13cdfa53a0490dd0d4	1777931988792	\N	1e0dc30f-c899-4c89-bd69-e95c31ff85b9
97	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777826351387__001.png	history/panels/panel_right_top/1777826351387__001.png	45b2c375f4ada8559a02df5c25e37bca563c67936e7a64b0b780719e9e7fc745	1777931988793	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
98	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777826351483__002.png	history/panels/panel_right_top/1777826351483__002.png	10f156b014176284ba20ef0076aee3fa18f2dfb0ffd1f2f5f3d4d68ed52c6984	1777931988795	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
99	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777826351676__003.png	history/panels/panel_right_top/1777826351676__003.png	76fa6b5aa7c45e41b2dbcbe535c2345645c1f551d47917b2f0629cc1b97495a3	1777931988795	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
100	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777826351807__004.png	history/panels/panel_right_top/1777826351807__004.png	b8cec88879c55bcfee4b5d5ac50aae68054219148b947649b17e63f23fa7cab0	1777931988796	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
101	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777844606511__005.png	history/panels/panel_right_top/1777844606511__005.png	d5d794d1381a04ef378d51afe513f4627c22eb72d228de32d9abe1be38a0e3c3	1777931988797	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
102	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777844606580__006.png	history/panels/panel_right_top/1777844606580__006.png	826ec96ce26270fcd8081fb059f946947a15befbfe1f352243f6d1970fbf4ce5	1777931988798	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
103	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777844606651__007.png	history/panels/panel_right_top/1777844606651__007.png	b08e5f7186404df15f6eadc28aa5c1443441e69c1503f666d360e7b97e8affcd	1777931988799	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
104	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777844606722__008.png	history/panels/panel_right_top/1777844606722__008.png	820628d9a061012f968c391abefd2441fe4451f922360ff2fa2a89d351965126	1777931988801	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
105	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777844783903__009.png	history/panels/panel_right_top/1777844783903__009.png	fc5ff4c69f66976ba27395bfee29be5c7104fe6bf3f3df1fbd203abe3350e342	1777931988802	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
106	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777844783973__010.png	history/panels/panel_right_top/1777844783973__010.png	93e4fc3609765fae0b4281ed86a6c264a758e7566536ef87e5a09e031e199a13	1777931988803	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
107	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777844784044__011.png	history/panels/panel_right_top/1777844784044__011.png	76d5a39bdab382e4b34d6c8c3ef79296dd585bd45cd0f670fc9c43a97cad4d05	1777931988806	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
108	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777844784116__012.png	history/panels/panel_right_top/1777844784116__012.png	984e402b1442749334ba2e100176ca4205b0202f33ab209326a0c5f73d13fa10	1777931988807	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
109	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777845170638__013.png	history/panels/panel_right_top/1777845170638__013.png	a843725030842b6e852f6add7ea111a5c53dde1445510fa989f9f014e8e8f193	1777931988807	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
110	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777845170712__014.png	history/panels/panel_right_top/1777845170712__014.png	8767fa964cfd85596f1808f9a8668203f1eb94bd53c4fb76d4ed336394a82087	1777931988808	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
111	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777845170782__015.png	history/panels/panel_right_top/1777845170782__015.png	801f08cd4965f69dd60cd87d3f77f1da682c0819c6099697d67dc2877f4a1a51	1777931988808	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
112	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777845170862__016.png	history/panels/panel_right_top/1777845170862__016.png	c3f6b42b34b80e0c51654a08d1c0abbaf692cc21c8e87e33e02df3025cef2b88	1777931988810	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
113	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777846720797__017.png	history/panels/panel_right_top/1777846720797__017.png	efbad95419d2e3a25652f0052781b10bc30fbc0989acdc78636836e3221f17ec	1777931988810	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
114	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777846720887__018.png	history/panels/panel_right_top/1777846720887__018.png	47416b5cedfb348d78a1ec02faeda0c3dafdcdd7f7793b9a62eeaa345e695437	1777931988810	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
115	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777846720957__019.png	history/panels/panel_right_top/1777846720957__019.png	af6f41d16113fc29479a27b0d8ea6a4229913ba23db6cf9287ec8b0d4cb2a136	1777931988818	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
116	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777846721027__020.png	history/panels/panel_right_top/1777846721027__020.png	e79121258e6f13a3285a33153fe28696dcb4829ac33d9e588abd042bf5199817	1777931988822	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
117	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777846878006__021.png	history/panels/panel_right_top/1777846878006__021.png	c5c3ffb9d84cc89c5e446a9f018e133bc497031785cf196304f499b4f0f3b680	1777931988835	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
118	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777846878093__022.png	history/panels/panel_right_top/1777846878093__022.png	cc25708c3d92ea232a840a1faf5aae999ba3c1c1fbb26b2305f04f4430842ec9	1777931988836	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
119	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777846878173__023.png	history/panels/panel_right_top/1777846878173__023.png	2206e33f83a6532611a8b0e286dcd53e008cb81cf566e2ef2af2dd7550b00848	1777931988837	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
120	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panels	panel_right_top	1777846878251__024.png	history/panels/panel_right_top/1777846878251__024.png	c4ef8706accbb833943726582b59afd65da3227fca80c9512779c220f0237200	1777931988838	\N	90e7b5fd-b225-4070-a5a7-6ab0b2c20704
121	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_banner_a	1777823149016__001.png	history/spaces/bottom_banner_a/1777823149016__001.png	e97c121faf3d0e360721251082f8a3011d59a2631e135c25d777c4fcd356fa3c	1777931988839	\N	d313c7b5-9929-4cda-9c93-a89e50dbaf2f
122	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_banner_a	1777823149059__002.png	history/spaces/bottom_banner_a/1777823149059__002.png	c87dee07db6c2c203b22401b3538d046fb8bf8513599993d9884cf683a48e363	1777931988843	\N	d313c7b5-9929-4cda-9c93-a89e50dbaf2f
123	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_banner_a	1777823149108__003.png	history/spaces/bottom_banner_a/1777823149108__003.png	b59f5172628b2097693827cb608b27637f244705fabf37af52e940adfd4f68d3	1777931988844	\N	d313c7b5-9929-4cda-9c93-a89e50dbaf2f
124	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_banner_b	1777823226221__001.png	history/spaces/bottom_banner_b/1777823226221__001.png	9bf32ad6ea2ca2dcaa80ad13921977e8161d7e75f86496f6be7ca02ac80df80a	1777931988845	\N	6265da1c-009c-4cd4-b152-e1f66670471d
125	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_banner_b	1777823226260__002.png	history/spaces/bottom_banner_b/1777823226260__002.png	cf71dd64e6142b973207fd259c1e031ee95ec3bad3e3cfdabd308a9a3a9cc79e	1777931988866	\N	6265da1c-009c-4cd4-b152-e1f66670471d
126	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_banner_b	1777823226299__003.png	history/spaces/bottom_banner_b/1777823226299__003.png	ab4d846865d5b66d0e8b9878b1e7abda7cb61b0742daa0a8a2037ae037445321	1777931988866	\N	6265da1c-009c-4cd4-b152-e1f66670471d
127	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_battle	1777823951501__001.png	history/spaces/bottom_battle/1777823951501__001.png	7e945abce152b65a41fcd949cb6830daa3188f610ac27533e5be2559b98f45a4	1777931988867	\N	0598d0b9-b2a9-4b75-9748-271f7e455eb7
128	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_battle	1777823951538__002.png	history/spaces/bottom_battle/1777823951538__002.png	42ea17c71a1ca4bc2827e02752067d94c26b76c4653ce2a3043e6121acae1e24	1777931988867	\N	0598d0b9-b2a9-4b75-9748-271f7e455eb7
129	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_battle	1777823951576__003.png	history/spaces/bottom_battle/1777823951576__003.png	177bf500ad9209f02e8c5a379b94803d99d1c3be7ddf8299f1349e9eafd25443	1777931988867	\N	0598d0b9-b2a9-4b75-9748-271f7e455eb7
130	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_a	1777823302497__001.png	history/spaces/bottom_space_a/1777823302497__001.png	ae39ef114f4718d08c0d9db606a1ea9dd6d53f94531d3444b76c1fd59fb4fb3f	1777931988868	\N	08e47ed0-a9ec-492b-af8b-7594e773b73f
131	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_a	1777823302536__002.png	history/spaces/bottom_space_a/1777823302536__002.png	27b6918c3fb68c4536210af9180d447450522fb8255c3a42a30d9fa3a96341d9	1777931988868	\N	08e47ed0-a9ec-492b-af8b-7594e773b73f
132	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_a	1777823302576__003.png	history/spaces/bottom_space_a/1777823302576__003.png	f9312aba46f8d8fe543f4b789f47561b953d26da36116b7b2518f09cc979dfe0	1777931988868	\N	08e47ed0-a9ec-492b-af8b-7594e773b73f
133	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_b	1777823379347__001.png	history/spaces/bottom_space_b/1777823379347__001.png	55581bef1955a72445874233a865b70c4174ad3202ab980c9d9f929fb78d6246	1777931988869	\N	e334954a-a8fb-40cb-ae6d-5f61740b55ab
134	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_b	1777823379386__002.png	history/spaces/bottom_space_b/1777823379386__002.png	3e16ab0301dd9a01efc9058bbd66882ddfaff1ddf7b6818888843ba873376d1f	1777931988869	\N	e334954a-a8fb-40cb-ae6d-5f61740b55ab
135	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_b	1777823379426__003.png	history/spaces/bottom_space_b/1777823379426__003.png	76ee3781da290d09e9e3e70123bffc95221f4d8b4296710a5385c8d0b8e8a3b7	1777931988869	\N	e334954a-a8fb-40cb-ae6d-5f61740b55ab
136	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_c	1777823456828__001.png	history/spaces/bottom_space_c/1777823456828__001.png	315d76e4f8688ec6f261ec4c0280fd57f73ca9816142fe8a8d73a81c3d1bc95e	1777931988870	\N	9f296306-f1f5-4cbb-a34b-7ab58fb695af
137	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_c	1777823456867__002.png	history/spaces/bottom_space_c/1777823456867__002.png	9e653644ff6905693d172591c22b6fc04290b67e9eae9fac72b7e3b240a96c8e	1777931988870	\N	9f296306-f1f5-4cbb-a34b-7ab58fb695af
138	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_c	1777823456904__003.png	history/spaces/bottom_space_c/1777823456904__003.png	d2a03276973590325df832b62dc94d4d2b8fdc1a4323cddd9ae062e85df8f479	1777931988870	\N	9f296306-f1f5-4cbb-a34b-7ab58fb695af
139	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_d	1777826465363__001.png	history/spaces/bottom_space_d/1777826465363__001.png	24bdf3ff4649ff6abe38a32e960bed120a75fdc4e56acf517aa14ebaa03ecef8	1777931988871	\N	0f27144e-1bf7-4c17-a23e-dc53d2881d92
140	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_d	1777826465401__002.png	history/spaces/bottom_space_d/1777826465401__002.png	569a5b88373569ec443beedbcdb340eea822962aeb0fbabf9e4252e77756b7b8	1777931988872	\N	0f27144e-1bf7-4c17-a23e-dc53d2881d92
141	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	bottom_space_d	1777826465442__003.png	history/spaces/bottom_space_d/1777826465442__003.png	b5ddd331f4654d52fc354ca7eef876fbb1e22cdec62965401cb6f66f69e1bb23	1777931988873	\N	0f27144e-1bf7-4c17-a23e-dc53d2881d92
142	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_bl	1777822581814__001.png	history/spaces/corner_bl/1777822581814__001.png	8cf56ff43b734988d9484a8cba5ce639e602efef545ed10fb5df27b2ef8abdfd	1777931988873	\N	85aa67aa-e1a5-4791-b59b-b2acbbbc264e
143	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_bl	1777822581954__002.png	history/spaces/corner_bl/1777822581954__002.png	28a0e555eccc707a2e14df4e117b8c11b457d03c89c5962ff8ec2207202fa6ab	1777931988874	\N	85aa67aa-e1a5-4791-b59b-b2acbbbc264e
144	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_bl	1777822582196__003.png	history/spaces/corner_bl/1777822582196__003.png	ae329203d459787323adfd48d1767a024a56e17ec5c76a7ae8e204c478049b9a	1777931988874	\N	85aa67aa-e1a5-4791-b59b-b2acbbbc264e
145	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_bl	1777845333831__004.png	history/spaces/corner_bl/1777845333831__004.png	de38c71cacf19d7ad12eadffc62375777858b3eb6777a69d28eae98627fc6d91	1777931988875	\N	85aa67aa-e1a5-4791-b59b-b2acbbbc264e
146	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_bl	1777845333874__005.png	history/spaces/corner_bl/1777845333874__005.png	be91939bb78c0f270cb5e58aab6e490469af17abb80ac5092872d79240a9792e	1777931988875	\N	85aa67aa-e1a5-4791-b59b-b2acbbbc264e
147	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_bl	1777845333912__006.png	history/spaces/corner_bl/1777845333912__006.png	fd176746c5917028706ee58b15e0ae4c461cce8145b06430b9d153984a70a888	1777931988875	\N	85aa67aa-e1a5-4791-b59b-b2acbbbc264e
148	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_br	1777822669625__001.png	history/spaces/corner_br/1777822669625__001.png	b715489be93cfba40786569f34b830d6308b21dfd0a8514d57f73c71a4032175	1777931988877	\N	082877ca-ecfb-4a41-aa0d-cf563b0b5da3
149	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_br	1777822669955__002.png	history/spaces/corner_br/1777822669955__002.png	e3943aaee02eaa8e8374f7486babc4901e0581d6057661179b09b3b4125b1fc7	1777931988877	\N	082877ca-ecfb-4a41-aa0d-cf563b0b5da3
150	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_br	1777822670420__003.png	history/spaces/corner_br/1777822670420__003.png	fdbca4765e37dc445b510c552993f73831542dd921c1af11c941918fea5d1b3b	1777931988879	\N	082877ca-ecfb-4a41-aa0d-cf563b0b5da3
151	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_tl	1777822349039__001.png	history/spaces/corner_tl/1777822349039__001.png	b3347b628203635ad7f6843b82caa4f7dd25e25caa35fd12623006de8dade4a9	1777931988879	\N	3c8b63b3-f8a3-47a7-acea-be76a2c60b12
152	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_tl	1777822349127__002.png	history/spaces/corner_tl/1777822349127__002.png	af2a52370a9a75d45882725bcabe68405274923c55e85dfdcaa6bf8be4e695a6	1777931988879	\N	3c8b63b3-f8a3-47a7-acea-be76a2c60b12
153	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_tl	1777822349212__003.png	history/spaces/corner_tl/1777822349212__003.png	a00647d53022c720de82045b97faeb83b16cad2f1e996b7bc7e08dd4bad8463d	1777931988880	\N	3c8b63b3-f8a3-47a7-acea-be76a2c60b12
154	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_tr	1777822500126__001.png	history/spaces/corner_tr/1777822500126__001.png	52e749defa8464d51018174932183672620e06d925a0aebc0fcf1f5cd914b935	1777931988880	\N	872ef89e-b657-4aa3-a111-ecfd53a28ad6
155	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_tr	1777822500265__002.png	history/spaces/corner_tr/1777822500265__002.png	390f38925dff3cdd9321f5fd5657d34074b6721d9a0d3d637e3bb2be28fe13dd	1777931988881	\N	872ef89e-b657-4aa3-a111-ecfd53a28ad6
156	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	corner_tr	1777822500429__003.png	history/spaces/corner_tr/1777822500429__003.png	cd4219de7956ad1a7ae6eb019fb28ea2926b5285adf852669f53bb2319ac31a3	1777931988881	\N	872ef89e-b657-4aa3-a111-ecfd53a28ad6
157	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	side_battle	1777824119773__001.png	history/spaces/side_battle/1777824119773__001.png	2a99d5cd297c4dabaed3f802c5081e1a113b06d2fae05178e0a6dd7e7c804c1f	1777931988881	\N	28c15232-e56e-4e43-ad03-b0867b84f00c
158	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	side_battle	1777824119822__002.png	history/spaces/side_battle/1777824119822__002.png	3a0b2b98278538a332a995e4ea5f69a4e11e552c79117422f4887b6bcac75b76	1777931988882	\N	28c15232-e56e-4e43-ad03-b0867b84f00c
159	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	side_battle	1777824119862__003.png	history/spaces/side_battle/1777824119862__003.png	7841db26f92e883db0992d5cd718845f7422d2d231209945d4dacbc6b7600ae8	1777931988882	\N	28c15232-e56e-4e43-ad03-b0867b84f00c
160	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	side_property	1777824043927__001.png	history/spaces/side_property/1777824043927__001.png	74d55bbe362d628cb2981d1e494922298f95a8d154b17ff0e5b879b5e6eb8053	1777931988882	\N	0b9f3635-5d2b-42b7-ad39-e1c63f6525cc
161	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	side_property	1777824043966__002.png	history/spaces/side_property/1777824043966__002.png	88fdc9ff114bb4166725aa99771d0119e28779c0970dfe1719cf57d0d9ba79f7	1777931988883	\N	0b9f3635-5d2b-42b7-ad39-e1c63f6525cc
162	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	side_property	1777824044006__003.png	history/spaces/side_property/1777824044006__003.png	cbbdcb7da9e4f4579dcb861b3363547bdf4f58908f6b79cc6f489357c55136c0	1777931988884	\N	0b9f3635-5d2b-42b7-ad39-e1c63f6525cc
163	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_banner_a	1777822750329__001.png	history/spaces/top_banner_a/1777822750329__001.png	f6d2468eaf89e2f09209637536278e4b9903832cc515e01fd59ccd27505876f0	1777931988884	\N	d55dea7d-d53d-45c6-b6da-a692ae542065
164	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_banner_a	1777822750841__002.png	history/spaces/top_banner_a/1777822750841__002.png	9d39f8129f1ec50de78064560af101c59d1e1e99698051627e321330ab5232c9	1777931988884	\N	d55dea7d-d53d-45c6-b6da-a692ae542065
165	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_banner_a	1777822751181__003.png	history/spaces/top_banner_a/1777822751181__003.png	ae5df38bcd685c9e317675681994575175e5868f8530be62e938e96fdf1abee9	1777931988885	\N	d55dea7d-d53d-45c6-b6da-a692ae542065
166	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_banner_b	1777822836190__001.png	history/spaces/top_banner_b/1777822836190__001.png	d3974c80b80ebb6877470e0986f9f59792cb18b4939c639b261147acb6fba60a	1777931988885	\N	0f4e58ce-6367-46db-a2a3-bff5fb9ed14c
167	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_banner_b	1777822836235__002.png	history/spaces/top_banner_b/1777822836235__002.png	cc6ca9e27068264f00c215c8d7123ba824c9cb2d889e8314ae8b76fa0f02ee89	1777931988885	\N	0f4e58ce-6367-46db-a2a3-bff5fb9ed14c
168	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_banner_b	1777822836284__003.png	history/spaces/top_banner_b/1777822836284__003.png	c6c6645e8dbc64117efe2edf4ade8a88a4d1e16a1063a3e53d06bb58d213a4dc	1777931988886	\N	0f4e58ce-6367-46db-a2a3-bff5fb9ed14c
169	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_battle	1777824202671__001.png	history/spaces/top_battle/1777824202671__001.png	bbff2a7da7d850b6e4d994e21c2d6c07f60fb536c1ec0fb6fe8591f3203d46a6	1777931988886	\N	7caa3c37-1794-49ca-9c65-cbe90c6d81df
170	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_battle	1777824202710__002.png	history/spaces/top_battle/1777824202710__002.png	83628c0a4de2aa028911ecb960e06f1cbf8ddedefc83544c439ef43e3e5364db	1777931988887	\N	7caa3c37-1794-49ca-9c65-cbe90c6d81df
171	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_battle	1777824202750__003.png	history/spaces/top_battle/1777824202750__003.png	b38312a121fca648501a9cb509e92bcb8270726fcb7e0a259f6dae7e6aa9df39	1777931988887	\N	7caa3c37-1794-49ca-9c65-cbe90c6d81df
172	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_space_a	1777822918326__001.png	history/spaces/top_space_a/1777822918326__001.png	d332727ae9e9d718c065bae1a34512843808f8894c399d3a2852d6053f2c6a85	1777931988888	\N	3eb21e06-e33c-4a97-88b4-04c55309fbca
173	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_space_a	1777822918366__002.png	history/spaces/top_space_a/1777822918366__002.png	84534779c2a2ac4e7e25c2b67a9ae3589285b290b5a41633090abe18f09ce9c6	1777931988889	\N	3eb21e06-e33c-4a97-88b4-04c55309fbca
174	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_space_a	1777822918410__003.png	history/spaces/top_space_a/1777822918410__003.png	a92f9943f27ef12e37f2c3fcd4b44be3d9f2780a0351cde065343bfdbaaa77b2	1777931988889	\N	3eb21e06-e33c-4a97-88b4-04c55309fbca
175	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_space_b	1777822996799__001.png	history/spaces/top_space_b/1777822996799__001.png	268ce516a59d00e1341832e21d761d9be319aa23b9d3ba416503d85b56400321	1777931988889	\N	15908a34-82c3-4044-82f5-be891a18d2eb
176	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_space_b	1777822996842__002.png	history/spaces/top_space_b/1777822996842__002.png	2ab04fc43117f59a64c2485b5657a4522f1031d9800b6d7ecaae6c8b4cfbce58	1777931988890	\N	15908a34-82c3-4044-82f5-be891a18d2eb
177	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_space_b	1777822996881__003.png	history/spaces/top_space_b/1777822996881__003.png	763b95c2450eb21b8c8bfc8d6b6d52348328d9e05ac92a8f13aef8c88863e2e5	1777931988890	\N	15908a34-82c3-4044-82f5-be891a18d2eb
178	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_space_c	1777823071436__001.png	history/spaces/top_space_c/1777823071436__001.png	e10711061ff8bc030432275cbc318158b7407d7c73f4685fa2a615290d01066a	1777931988891	\N	d14b42cb-f4b1-4b0d-aeed-5c107ca6c915
179	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_space_c	1777823071475__002.png	history/spaces/top_space_c/1777823071475__002.png	8d9d12849c61a828e2a7cba17b5c9c283ec17ab986fb32b181cd649aaf8de7d8	1777931988891	\N	d14b42cb-f4b1-4b0d-aeed-5c107ca6c915
180	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	spaces	top_space_c	1777823071513__003.png	history/spaces/top_space_c/1777823071513__003.png	324cdac0a88c20de152933d098a373772c8ce44637e8703a0c79dbd1042fb877	1777931988892	\N	d14b42cb-f4b1-4b0d-aeed-5c107ca6c915
181	ef5082cd-a41e-4319-9b9d-1f42842a518c	centerpiece	centerpiece	1777783027976__001.png	history/centerpiece/centerpiece/1777783027976__001.png	206e424a32b07100210746e7e67052306f62950f9be4e666d5647e5568d60e17	1777931988627	\N	340d35b6-5e84-4d0f-8f44-a120dd3fed4e
182	ef5082cd-a41e-4319-9b9d-1f42842a518c	centerpiece	centerpiece	1777783028756__002.png	history/centerpiece/centerpiece/1777783028756__002.png	89d78cd4b11f5fac285b954583e094a256610cc731c2fc0671433a8a1a101db8	1777931988628	\N	340d35b6-5e84-4d0f-8f44-a120dd3fed4e
183	ef5082cd-a41e-4319-9b9d-1f42842a518c	centerpiece	centerpiece	1777783029603__003.png	history/centerpiece/centerpiece/1777783029603__003.png	5fb436c58863b4b7cc5a8f83358c22bcab611809adc6d2402ce12b1e20a11936	1777931988629	\N	340d35b6-5e84-4d0f-8f44-a120dd3fed4e
184	ef5082cd-a41e-4319-9b9d-1f42842a518c	centerpiece	centerpiece	1777783030334__004.png	history/centerpiece/centerpiece/1777783030334__004.png	bdef57bfc845741cfa14ac8ba51b037092db130d9772a6c0df481e91dd84a193	1777931988631	\N	340d35b6-5e84-4d0f-8f44-a120dd3fed4e
185	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cleft_mid	1777783098001__001.png	history/panels/panel_cleft_mid/1777783098001__001.png	ea81882f6ee3b8c5ca58afdec83dc668fe1f5856d6e6df4a249a80c1c6687a5c	1777931988632	\N	97462309-ed19-49c8-9634-4b89d6b55279
186	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cleft_mid	1777783098151__002.png	history/panels/panel_cleft_mid/1777783098151__002.png	e9e18e575a7d20d9c4782cf8c0b8fa05cd3e49b6947fb109b8cea48cd65e30d7	1777931988633	\N	97462309-ed19-49c8-9634-4b89d6b55279
187	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cleft_mid	1777783098262__003.png	history/panels/panel_cleft_mid/1777783098262__003.png	79abd4821e37ea7e576ad8527830ceb6ab61325178ea6b367aa150121df0b440	1777931988635	\N	97462309-ed19-49c8-9634-4b89d6b55279
188	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cleft_mid	1777783098396__004.png	history/panels/panel_cleft_mid/1777783098396__004.png	4447bf7ac106a24ef7514aedf75083abd14729db5dc7c56bc6b0cb15176c2b48	1777931988636	\N	97462309-ed19-49c8-9634-4b89d6b55279
189	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cleft_top	1777864856627__001.png	history/panels/panel_cleft_top/1777864856627__001.png	7520054eeab53cb6965c025487d5c4219c9626843cd06df97fbeea1e16ed2c31	1777931988637	\N	fcd48d2a-f280-4e23-ab19-a2becede633b
190	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cleft_top	1777864856725__002.png	history/panels/panel_cleft_top/1777864856725__002.png	9ac042e3ce847e724de941005b8cdd60a4124071cb10b3fa81567138eef93432	1777931988641	\N	fcd48d2a-f280-4e23-ab19-a2becede633b
191	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cleft_top	1777864856814__003.png	history/panels/panel_cleft_top/1777864856814__003.png	bb2f1258b5683000035782ca71548375f546347859b900241c82c23502e61f35	1777931988642	\N	fcd48d2a-f280-4e23-ab19-a2becede633b
192	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cright_mid	1777782967967__001.png	history/panels/panel_cright_mid/1777782967967__001.png	4f2dce4a0f846c878e7a4a466155e23e44a819792837a2d3a9b83ee9de2ee5ec	1777931988643	\N	1c6fd98d-794c-459f-a733-deb2b37068c0
193	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cright_mid	1777782968096__002.png	history/panels/panel_cright_mid/1777782968096__002.png	6635ad0bcb6c96ed80eeadb13086a6c6f934d3944c684258835ac9a279030718	1777931988644	\N	1c6fd98d-794c-459f-a733-deb2b37068c0
194	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cright_mid	1777782968222__003.png	history/panels/panel_cright_mid/1777782968222__003.png	57ab4cced4bea34322cec582d63ef93b964f9b1f1bb67510ca94db3ac4639982	1777931988644	\N	1c6fd98d-794c-459f-a733-deb2b37068c0
195	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cright_mid	1777782968333__004.png	history/panels/panel_cright_mid/1777782968333__004.png	04f93edac6ad596ee06c131290c42aaf90d5c5be2ac4f81067feea0b91222135	1777931988645	\N	1c6fd98d-794c-459f-a733-deb2b37068c0
196	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cright_top	1777864809306__001.png	history/panels/panel_cright_top/1777864809306__001.png	3d7528274d25119c070b2a691babb1877498ad2649f226ebf86ceb7ee2f00ba3	1777931988645	\N	e6b7c247-6302-4858-9d0e-8c58946dcca2
197	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cright_top	1777864809418__002.png	history/panels/panel_cright_top/1777864809418__002.png	3407aae00966c6a3e875a85666bf6010b500562305dfb7e7e6d5767fe0ed3bd0	1777931988646	\N	e6b7c247-6302-4858-9d0e-8c58946dcca2
198	ef5082cd-a41e-4319-9b9d-1f42842a518c	panels	panel_cright_top	1777864809523__003.png	history/panels/panel_cright_top/1777864809523__003.png	1129be5aa46c5917b2459805fe21da535ddf77a0845bff16557850d0332e6c59	1777931988646	\N	e6b7c247-6302-4858-9d0e-8c58946dcca2
199	ef5082cd-a41e-4319-9b9d-1f42842a518c	spaces	side_battle	1777865399983__001.png	history/spaces/side_battle/1777865399983__001.png	96a667672c8a1b235c329503de547aee99ec393866cc4160853c9321d355b166	1777931988647	\N	b5d2070d-0f7c-4a34-8c26-ade28f2d3dc6
200	ef5082cd-a41e-4319-9b9d-1f42842a518c	spaces	side_battle	1777865400392__002.png	history/spaces/side_battle/1777865400392__002.png	31fd03f73252d670a638af8418c8c4b3cd736f38ca61f791cb85812d80461ef6	1777931988647	\N	b5d2070d-0f7c-4a34-8c26-ade28f2d3dc6
201	ef5082cd-a41e-4319-9b9d-1f42842a518c	spaces	side_battle	1777865400938__003.png	history/spaces/side_battle/1777865400938__003.png	7aacf522defd61283d3055d697c306657f2cbf2ad1d42521fd7d06ff8a5bcc7b	1777931988647	\N	b5d2070d-0f7c-4a34-8c26-ade28f2d3dc6
202	ef5082cd-a41e-4319-9b9d-1f42842a518c	spaces	top_battle	1777782913715__001.png	history/spaces/top_battle/1777782913715__001.png	e90544446ab5765e0d869fc7b5c07416e3fe88469219e0e2d30d2c645caa2df1	1777931988648	\N	8bdc06ef-b5e1-4b68-bc9f-98a6fa7ebe12
203	ef5082cd-a41e-4319-9b9d-1f42842a518c	spaces	top_battle	1777782913766__002.png	history/spaces/top_battle/1777782913766__002.png	fb4f77f21d7b218df074355c0bec0a614ec22ac4945e065eb83c6f6732122b0f	1777931988648	\N	8bdc06ef-b5e1-4b68-bc9f-98a6fa7ebe12
204	ef5082cd-a41e-4319-9b9d-1f42842a518c	spaces	top_battle	1777782913814__003.png	history/spaces/top_battle/1777782913814__003.png	67c0659064961d684f717dd15174998badcf2821a801feaa740597e3506675ca	1777931988649	\N	8bdc06ef-b5e1-4b68-bc9f-98a6fa7ebe12
\.


--
-- Data for Name: board_games; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.board_games (id, body_json, updated_ms, palette_json, palette_gpl_text, style_lock_updated_ms, project, board_size_w, board_size_h, palette_size, provider, openai_model, openai_quality, pixellab_model, generation_configured, frame_enabled, frame_apply_to_panels, frame_apply_to_spaces, style_reference_image, style_prompt) FROM stdin;
748e880d-ceab-46e3-96f8-7684903a2727	{"board_spaces": {"layout": {"top_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 0], "spacing": 160}, "left_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [0, 180], "spacing": 144}, "right_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [1740, 180], "spacing": 144}, "bottom_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 900], "spacing": 160}}}}	1777785247950	[[209, 161, 60], [186, 164, 58], [186, 142, 49], [178, 130, 48], [121, 163, 70], [103, 172, 60], [117, 134, 62], [56, 151, 60], [46, 133, 65], [191, 105, 54], [200, 79, 49], [134, 107, 57], [135, 73, 61], [63, 112, 59], [38, 116, 70], [56, 96, 70], [69, 76, 42], [38, 78, 56], [183, 43, 56], [139, 43, 57], [94, 29, 56], [60, 29, 43], [40, 22, 22], [33, 47, 74]]	GIMP Palette\nName: BoardFactory (24 colors)\nColumns: 8\n#\n209 161  60\tRGB-d1a13c\n186 164  58\tRGB-baa43a\n186 142  49\tRGB-ba8e31\n178 130  48\tRGB-b28230\n121 163  70\tRGB-79a346\n103 172  60\tRGB-67ac3c\n117 134  62\tRGB-75863e\n 56 151  60\tRGB-38973c\n 46 133  65\tRGB-2e8541\n191 105  54\tRGB-bf6936\n200  79  49\tRGB-c84f31\n134 107  57\tRGB-866b39\n135  73  61\tRGB-87493d\n 63 112  59\tRGB-3f703b\n 38 116  70\tRGB-267446\n 56  96  70\tRGB-386046\n 69  76  42\tRGB-454c2a\n 38  78  56\tRGB-264e38\n183  43  56\tRGB-b72b38\n139  43  57\tRGB-8b2b39\n 94  29  56\tRGB-5e1d38\n 60  29  43\tRGB-3c1d2b\n 40  22  22\tRGB-281616\n 33  47  74\tRGB-212f4a\n	1777934568506	damnation	1920	1080	36	openai	gpt-image-1	medium	pixflux_sharp	t	f	t	f	mockup/board.png	
02ad5018-b82e-49ce-ad23-43d20ff06c9d	{"board_spaces": {"layout": {"top_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 0], "spacing": 160}, "left_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [0, 180], "spacing": 144}, "right_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [1740, 180], "spacing": 144}, "bottom_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 900], "spacing": 160}}}}	1777785226992	[[243, 197, 167], [241, 189, 159], [239, 185, 154], [241, 181, 151], [234, 179, 150], [235, 178, 141], [224, 178, 157], [237, 169, 153], [225, 170, 155], [230, 167, 138], [217, 165, 149], [231, 154, 147], [221, 156, 145], [222, 153, 127], [227, 141, 133], [217, 140, 125], [213, 145, 124], [211, 138, 117], [211, 132, 115], [196, 136, 115], [207, 122, 111], [192, 119, 101], [190, 104, 100], [177, 98, 92], [172, 97, 89], [171, 90, 89], [164, 91, 83], [148, 93, 78], [157, 80, 80], [147, 78, 75], [146, 74, 75], [143, 67, 70], [128, 66, 62], [109, 63, 52], [105, 49, 48], [79, 39, 35]]	GIMP Palette\nName: BoardFactory (36 colors)\nColumns: 8\n#\n243 197 167\tRGB-f3c5a7\n241 189 159\tRGB-f1bd9f\n239 185 154\tRGB-efb99a\n241 181 151\tRGB-f1b597\n234 179 150\tRGB-eab396\n235 178 141\tRGB-ebb28d\n224 178 157\tRGB-e0b29d\n237 169 153\tRGB-eda999\n225 170 155\tRGB-e1aa9b\n230 167 138\tRGB-e6a78a\n217 165 149\tRGB-d9a595\n231 154 147\tRGB-e79a93\n221 156 145\tRGB-dd9c91\n222 153 127\tRGB-de997f\n227 141 133\tRGB-e38d85\n217 140 125\tRGB-d98c7d\n213 145 124\tRGB-d5917c\n211 138 117\tRGB-d38a75\n211 132 115\tRGB-d38473\n196 136 115\tRGB-c48873\n207 122 111\tRGB-cf7a6f\n192 119 101\tRGB-c07765\n190 104 100\tRGB-be6864\n177  98  92\tRGB-b1625c\n172  97  89\tRGB-ac6159\n171  90  89\tRGB-ab5a59\n164  91  83\tRGB-a45b53\n148  93  78\tRGB-945d4e\n157  80  80\tRGB-9d5050\n147  78  75\tRGB-934e4b\n146  74  75\tRGB-924a4b\n143  67  70\tRGB-8f4346\n128  66  62\tRGB-80423e\n109  63  52\tRGB-6d3f34\n105  49  48\tRGB-693130\n 79  39  35\tRGB-4f2723\n	1777687802475	pink desert	1920	1080	24	openai	gpt-image-1	low	pixflux_sharp	t	t	t	f	mockup/board.png	The board evokes an ancient desert city with rich history, using a warm, earthy palette. Accents of pink, gold, and turquoise create a mystical and adventurous mood, complemented by pixel-art style with detailed textures.
ed1456f7-12ef-48d3-ac59-4c93634c8a33	{"board_spaces": {"layout": {"top_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 0], "spacing": 160}, "left_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [0, 180], "spacing": 144}, "right_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [1740, 180], "spacing": 144}, "bottom_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 900], "spacing": 160}}}}	1777687089499	\N	\N	\N	fantasy-quest	1920	1080	36	openai	gpt-image-2	low	pixflux_sharp	f	f	t	f	mockup/board.png	
2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	{"board_spaces": {"layout": {"top_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 0], "spacing": 160}, "left_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [0, 180], "spacing": 144}, "right_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [1740, 180], "spacing": 144}, "bottom_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 900], "spacing": 160}}}}	1777865442975	[[237, 208, 165], [219, 197, 149], [217, 193, 150], [238, 187, 136], [238, 187, 117], [199, 187, 138], [236, 177, 140], [234, 176, 112], [215, 175, 140], [171, 176, 144], [232, 161, 136], [230, 148, 128], [226, 159, 97], [223, 144, 88], [200, 148, 122], [196, 138, 142], [196, 143, 82], [191, 137, 81], [163, 149, 119], [221, 131, 89], [190, 134, 84], [186, 133, 88], [204, 120, 69], [199, 101, 59], [177, 127, 85], [175, 103, 63], [161, 103, 62], [132, 103, 68], [163, 75, 34], [131, 71, 30], [142, 53, 22], [115, 49, 17], [93, 50, 22], [80, 37, 11], [75, 34, 10], [67, 24, 5]]	GIMP Palette\nName: BoardFactory (36 colors)\nColumns: 8\n#\n237 208 165\tRGB-edd0a5\n219 197 149\tRGB-dbc595\n217 193 150\tRGB-d9c196\n238 187 136\tRGB-eebb88\n238 187 117\tRGB-eebb75\n199 187 138\tRGB-c7bb8a\n236 177 140\tRGB-ecb18c\n234 176 112\tRGB-eab070\n215 175 140\tRGB-d7af8c\n171 176 144\tRGB-abb090\n232 161 136\tRGB-e8a188\n230 148 128\tRGB-e69480\n226 159  97\tRGB-e29f61\n223 144  88\tRGB-df9058\n200 148 122\tRGB-c8947a\n196 138 142\tRGB-c48a8e\n196 143  82\tRGB-c48f52\n191 137  81\tRGB-bf8951\n163 149 119\tRGB-a39577\n221 131  89\tRGB-dd8359\n190 134  84\tRGB-be8654\n186 133  88\tRGB-ba8558\n204 120  69\tRGB-cc7845\n199 101  59\tRGB-c7653b\n177 127  85\tRGB-b17f55\n175 103  63\tRGB-af673f\n161 103  62\tRGB-a1673e\n132 103  68\tRGB-846744\n163  75  34\tRGB-a34b22\n131  71  30\tRGB-83471e\n142  53  22\tRGB-8e3516\n115  49  17\tRGB-733111\n 93  50  22\tRGB-5d3216\n 80  37  11\tRGB-50250b\n 75  34  10\tRGB-4b220a\n 67  24   5\tRGB-431805\n	1777822181122	I Luv Cake	1920	1080	36	openai	gpt-image-2	medium	pixflux_sharp	t	f	t	f	mockup/board.png	Whimsical, candyland theme with pastel colors. Accents include pink, mint green, lavender, and chocolate brown. The mood is playful and sweet, reminiscent of a fantasy confectionery world.
e92c3dc7-ec23-4f36-9f78-ee04abf6106b	{"board_spaces": {"layout": {"top_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 0], "spacing": 160}, "left_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [0, 180], "spacing": 144}, "right_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [1740, 180], "spacing": 144}, "bottom_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 900], "spacing": 160}}}}	1777699222186	[[192, 166, 116], [142, 124, 100], [138, 120, 97], [152, 96, 68], [129, 93, 79], [102, 89, 75], [133, 64, 50], [101, 66, 58], [93, 63, 57], [91, 57, 51], [83, 58, 53], [73, 56, 51], [160, 40, 38], [108, 34, 33], [75, 45, 41], [80, 29, 29], [63, 43, 41], [63, 39, 37], [61, 32, 32], [49, 36, 34], [43, 29, 29], [43, 24, 25], [32, 24, 23], [26, 22, 22]]	GIMP Palette\nName: BoardFactory (24 colors)\nColumns: 8\n#\n192 166 116\tRGB-c0a674\n142 124 100\tRGB-8e7c64\n138 120  97\tRGB-8a7861\n152  96  68\tRGB-986044\n129  93  79\tRGB-815d4f\n102  89  75\tRGB-66594b\n133  64  50\tRGB-854032\n101  66  58\tRGB-65423a\n 93  63  57\tRGB-5d3f39\n 91  57  51\tRGB-5b3933\n 83  58  53\tRGB-533a35\n 73  56  51\tRGB-493833\n160  40  38\tRGB-a02826\n108  34  33\tRGB-6c2221\n 75  45  41\tRGB-4b2d29\n 80  29  29\tRGB-501d1d\n 63  43  41\tRGB-3f2b29\n 63  39  37\tRGB-3f2725\n 61  32  32\tRGB-3d2020\n 49  36  34\tRGB-312422\n 43  29  29\tRGB-2b1d1d\n 43  24  25\tRGB-2b1819\n 32  24  23\tRGB-201817\n 26  22  22\tRGB-1a1616\n	1777934568510	revelation x 1	1920	1080	24	openai	gpt-image-1	low	pixflux_sharp	t	f	t	f	mockup/board.png	
ef5082cd-a41e-4319-9b9d-1f42842a518c	{"board_spaces": {"layout": {"top_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 0], "spacing": 160}, "left_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [0, 180], "spacing": 144}, "right_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [1740, 180], "spacing": 144}, "bottom_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 900], "spacing": 160}}}}	1777869553753	[[218, 213, 169], [208, 185, 118], [194, 157, 84], [128, 175, 164], [119, 145, 114], [159, 119, 60], [124, 114, 58], [92, 112, 73], [55, 111, 122], [120, 81, 44], [95, 71, 36], [74, 82, 44], [77, 58, 30], [42, 78, 88], [48, 74, 31], [38, 57, 55], [38, 57, 22], [79, 40, 27], [63, 35, 22], [54, 40, 26], [53, 20, 21], [39, 42, 37], [40, 37, 14], [39, 17, 20], [22, 42, 39], [22, 42, 18], [22, 29, 21], [24, 13, 16], [11, 36, 45], [8, 30, 39], [13, 31, 23], [8, 24, 29], [10, 22, 19], [6, 17, 19], [8, 14, 11], [4, 6, 5]]	GIMP Palette\nName: BoardFactory (36 colors)\nColumns: 8\n#\n218 213 169\tRGB-dad5a9\n208 185 118\tRGB-d0b976\n194 157  84\tRGB-c29d54\n128 175 164\tRGB-80afa4\n119 145 114\tRGB-779172\n159 119  60\tRGB-9f773c\n124 114  58\tRGB-7c723a\n 92 112  73\tRGB-5c7049\n 55 111 122\tRGB-376f7a\n120  81  44\tRGB-78512c\n 95  71  36\tRGB-5f4724\n 74  82  44\tRGB-4a522c\n 77  58  30\tRGB-4d3a1e\n 42  78  88\tRGB-2a4e58\n 48  74  31\tRGB-304a1f\n 38  57  55\tRGB-263937\n 38  57  22\tRGB-263916\n 79  40  27\tRGB-4f281b\n 63  35  22\tRGB-3f2316\n 54  40  26\tRGB-36281a\n 53  20  21\tRGB-351415\n 39  42  37\tRGB-272a25\n 40  37  14\tRGB-28250e\n 39  17  20\tRGB-271114\n 22  42  39\tRGB-162a27\n 22  42  18\tRGB-162a12\n 22  29  21\tRGB-161d15\n 24  13  16\tRGB-180d10\n 11  36  45\tRGB-0b242d\n  8  30  39\tRGB-081e27\n 13  31  23\tRGB-0d1f17\n  8  24  29\tRGB-08181d\n 10  22  19\tRGB-0a1613\n  6  17  19\tRGB-061113\n  8  14  11\tRGB-080e0b\n  4   6   5\tRGB-040605\n	1777699452042	rando board	1920	1080	24	openai	gpt-image-1	medium	pixflux_sharp	t	f	t	f	mockup/board.png	Fantasy-themed pixel art with intricate details. Bright, luminescent crystal blues, rich forest greens, golden sunlit tones, and deep amethyst purples create a magical and adventurous mood.
3de2757b-bbe2-4f74-9e36-d2e7d3285b48	{"board_spaces": {"layout": {"top_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 0], "spacing": 160}, "left_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [0, 180], "spacing": 144}, "right_col": {"axis": "y", "size": [180, 144], "count": 5, "start": [1740, 180], "spacing": 144}, "bottom_row": {"axis": "x", "size": [160, 180], "count": 12, "start": [0, 900], "spacing": 160}}}}	1777699202856	[[209, 189, 133], [175, 142, 99], [144, 124, 99], [134, 123, 102], [141, 120, 96], [132, 118, 99], [152, 96, 68], [129, 93, 79], [116, 90, 78], [85, 88, 72], [133, 64, 50], [101, 66, 58], [94, 65, 58], [93, 61, 55], [91, 57, 51], [84, 61, 56], [83, 53, 48], [77, 57, 52], [67, 55, 49], [160, 40, 38], [108, 34, 33], [75, 45, 41], [80, 29, 29], [63, 45, 42], [64, 40, 39], [63, 39, 37], [61, 35, 34], [61, 27, 28], [53, 37, 36], [45, 35, 33], [48, 30, 30], [38, 29, 28], [43, 24, 25], [32, 24, 23], [27, 24, 24], [25, 20, 20]]	GIMP Palette\nName: BoardFactory (36 colors)\nColumns: 8\n#\n209 189 133\tRGB-d1bd85\n175 142  99\tRGB-af8e63\n144 124  99\tRGB-907c63\n134 123 102\tRGB-867b66\n141 120  96\tRGB-8d7860\n132 118  99\tRGB-847663\n152  96  68\tRGB-986044\n129  93  79\tRGB-815d4f\n116  90  78\tRGB-745a4e\n 85  88  72\tRGB-555848\n133  64  50\tRGB-854032\n101  66  58\tRGB-65423a\n 94  65  58\tRGB-5e413a\n 93  61  55\tRGB-5d3d37\n 91  57  51\tRGB-5b3933\n 84  61  56\tRGB-543d38\n 83  53  48\tRGB-533530\n 77  57  52\tRGB-4d3934\n 67  55  49\tRGB-433731\n160  40  38\tRGB-a02826\n108  34  33\tRGB-6c2221\n 75  45  41\tRGB-4b2d29\n 80  29  29\tRGB-501d1d\n 63  45  42\tRGB-3f2d2a\n 64  40  39\tRGB-402827\n 63  39  37\tRGB-3f2725\n 61  35  34\tRGB-3d2322\n 61  27  28\tRGB-3d1b1c\n 53  37  36\tRGB-352524\n 45  35  33\tRGB-2d2321\n 48  30  30\tRGB-301e1e\n 38  29  28\tRGB-261d1c\n 43  24  25\tRGB-2b1819\n 32  24  23\tRGB-201817\n 27  24  24\tRGB-1b1818\n 25  20  20\tRGB-191414\n	1777934568493	revelation x 2	1920	1080	36	openai	gpt-image-2	medium	pixflux_sharp	t	f	t	f	mockup/board.png	
\.


--
-- Data for Name: browser_sessions; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.browser_sessions (sid, user_id, created_ms, last_seen_ms) FROM stdin;
8m1fomRi_SbjicZlBHWL4r3kj-sNk3e_	46c004b7a2a9482398aa262d103cf96e	1777682466977	1777923381036
LnZ7ZvRf5dDxciMtYz038Hn8JDxZoPLo	46c004b7a2a9482398aa262d103cf96e	1777822775286	1777870488690
a19fCUhrtBjPPSeWEU7nBmsGr4FriOWO	46c004b7a2a9482398aa262d103cf96e	1777932194496	1777939749114
6hoelKe_HlB9V-7StoOlqgQwCzeAzaMZ	46c004b7a2a9482398aa262d103cf96e	1777937643777	1777939801976
\.


--
-- Data for Name: cells; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.cells (id, board_uuid, kind, slug, position_index, prompt, needs_active, active_kind, space_kind, positions_json, bbox_x1, bbox_y1, bbox_x2, bbox_y2, target_w, target_h) FROM stdin;
38476bb0-1676-4ed0-93e9-99912c933a07	748e880d-ceab-46e3-96f8-7684903a2727	space	corner_tl	0		f	none	standard	["top_row.0"]	\N	\N	\N	\N	\N	\N
44bad422-75ee-4101-8d89-756f7510458c	748e880d-ceab-46e3-96f8-7684903a2727	space	corner_tr	1		f	none	standard	["top_row.11"]	\N	\N	\N	\N	\N	\N
c551c198-1369-4b74-ab97-63ae500f4673	748e880d-ceab-46e3-96f8-7684903a2727	space	corner_bl	2		f	none	standard	["bottom_row.0"]	\N	\N	\N	\N	\N	\N
684b2398-5144-4992-883b-43535a9d30fd	748e880d-ceab-46e3-96f8-7684903a2727	space	corner_br	3		f	none	standard	["bottom_row.11"]	\N	\N	\N	\N	\N	\N
e7fa6140-0edd-4cbd-b77f-5a1e22c2e02e	748e880d-ceab-46e3-96f8-7684903a2727	space	top_banner_a	4		f	none	standard	["top_row.5"]	\N	\N	\N	\N	\N	\N
fb347f50-3a23-47ec-ad49-8dd8b360ea9c	748e880d-ceab-46e3-96f8-7684903a2727	space	top_banner_b	5		f	none	standard	["top_row.7"]	\N	\N	\N	\N	\N	\N
c7a2cd72-6372-431f-88f6-b25a2cac5d41	748e880d-ceab-46e3-96f8-7684903a2727	space	top_space_a	6		f	none	standard	["top_row.1", "top_row.4", "top_row.8"]	\N	\N	\N	\N	\N	\N
0dec3e10-126c-4c8a-a608-095627ab4a07	748e880d-ceab-46e3-96f8-7684903a2727	space	top_space_b	7		f	none	standard	["top_row.2", "top_row.6", "top_row.9"]	\N	\N	\N	\N	\N	\N
50d7495f-e559-41e2-b70d-c75573e64970	748e880d-ceab-46e3-96f8-7684903a2727	space	top_space_c	8		f	none	standard	["top_row.3", "top_row.10"]	\N	\N	\N	\N	\N	\N
ed6ccf75-1c5a-400f-b87a-7253ad4aebc1	748e880d-ceab-46e3-96f8-7684903a2727	space	bottom_banner_a	9		f	none	standard	["bottom_row.5"]	\N	\N	\N	\N	\N	\N
026a7bf7-0af1-4b7c-8d37-3843235616d9	748e880d-ceab-46e3-96f8-7684903a2727	space	bottom_banner_b	10		f	none	standard	["bottom_row.6"]	\N	\N	\N	\N	\N	\N
fe4c5b8b-b385-4438-9802-b3ea587c9948	748e880d-ceab-46e3-96f8-7684903a2727	space	bottom_space_a	11		f	none	standard	["bottom_row.1", "bottom_row.4"]	\N	\N	\N	\N	\N	\N
eb024126-db41-40e0-a81c-7c261a4b23b5	748e880d-ceab-46e3-96f8-7684903a2727	space	bottom_space_b	12		f	none	standard	["bottom_row.2", "bottom_row.10"]	\N	\N	\N	\N	\N	\N
c969f7f6-adf3-4dc3-8849-86ab154b96f8	748e880d-ceab-46e3-96f8-7684903a2727	space	bottom_space_c	13		f	none	standard	["bottom_row.3", "bottom_row.8"]	\N	\N	\N	\N	\N	\N
3b19b24c-100f-4ba4-b453-35a3dcee0425	748e880d-ceab-46e3-96f8-7684903a2727	space	bottom_space_d	14		f	none	standard	["bottom_row.9"]	\N	\N	\N	\N	\N	\N
52eb0298-5aa0-439b-8469-4c6ba4a7c81f	748e880d-ceab-46e3-96f8-7684903a2727	space	bottom_battle	15		f	none	standard	["bottom_row.7"]	\N	\N	\N	\N	\N	\N
019cbae7-d4a1-447b-8a49-39ddeb92797b	748e880d-ceab-46e3-96f8-7684903a2727	space	side_property	16		f	none	standard	["left_col.0", "left_col.1", "left_col.3", "left_col.4", "right_col.1", "right_col.2", "right_col.3"]	\N	\N	\N	\N	\N	\N
1d9b4bd8-1b2b-4bb6-bc42-f2785553f40d	748e880d-ceab-46e3-96f8-7684903a2727	space	side_battle	17		f	none	standard	["left_col.2", "right_col.0", "right_col.4"]	\N	\N	\N	\N	\N	\N
69e7b559-b30d-4f23-938e-62ed503f477c	748e880d-ceab-46e3-96f8-7684903a2727	space	top_battle	18		f	none	standard	["top_row.3"]	\N	\N	\N	\N	\N	\N
f9b5fcfa-f427-443e-98e5-7734255b2f28	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	corner_tl	0	Grand castle with palm trees, sunset backdrop.	f	none	standard	["top_row.0"]	\N	\N	\N	\N	\N	\N
989b8b88-b7b1-418b-9248-6693690f30f3	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	corner_tr	1	Regal peacock perched elegantly, vibrant feathers.	f	none	standard	["top_row.11"]	\N	\N	\N	\N	\N	\N
19c9b66c-add6-4f0b-b5fd-ad64bc1fa110	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	corner_bl	2	Oasis with camels, serene desert sunset.	f	none	standard	["bottom_row.0"]	\N	\N	\N	\N	\N	\N
776fd603-24d6-4b96-802e-05674bc61770	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	corner_br	3	Ancient stone obelisk under the moonlight.	f	none	standard	["bottom_row.11"]	\N	\N	\N	\N	\N	\N
3306ff09-4e6d-451b-aa3e-35b09d42215c	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	top_banner_a	4	Golden hourglass, shimmering sand inside.	f	none	standard	["top_row.5"]	\N	\N	\N	\N	\N	\N
c213fc2e-5480-48c0-b25d-1d3b0a217bdc	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	top_banner_b	5	Mystical lamp with intricate designs.	f	none	standard	["top_row.7"]	\N	\N	\N	\N	\N	\N
8344c699-cc0b-4d66-9d3a-5b01993a942a	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	top_space_a	6	Tiled fountain with crystal-clear water.	f	none	standard	["top_row.1", "top_row.4", "top_row.8"]	\N	\N	\N	\N	\N	\N
23aefdd5-65a1-4902-9f60-b05157fa1be6	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	top_space_b	7	Cluster of pink crystals, enchanted glow.	f	none	standard	["top_row.2", "top_row.6", "top_row.9"]	\N	\N	\N	\N	\N	\N
789a7a1e-fa67-408f-b2f3-1dba4971f396	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	top_space_c	8	Camel caravan traversing endless sand dunes.	f	none	standard	["top_row.3", "top_row.10"]	\N	\N	\N	\N	\N	\N
dfc8b066-a709-477e-a0aa-cf4fbd0091c4	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	bottom_banner_a	9	Embroidered tapestry with desert motifs.	f	none	standard	["bottom_row.5"]	\N	\N	\N	\N	\N	\N
27fbb58c-6d4e-40b3-9964-d685609c6170	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	bottom_banner_b	10	Golden coins stack, gleaming under the sun.	f	none	standard	["bottom_row.6"]	\N	\N	\N	\N	\N	\N
bb44a0c1-9f3c-4533-a92f-e534a1f8e9ef	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	bottom_space_a	11	Rolling dunes dotted with solitary cacti.	f	none	standard	["bottom_row.1", "bottom_row.4"]	\N	\N	\N	\N	\N	\N
e54fd60d-7ce0-4669-90ee-2e9ffe4762bc	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	bottom_space_b	12	Scorpion poised under the scorching sun.	f	none	standard	["bottom_row.2", "bottom_row.10"]	\N	\N	\N	\N	\N	\N
a27236d4-7b9e-47b1-baf3-00b126461c17	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	bottom_space_c	13	Nomadic tent, vibrant fabrics, spices wafting.	f	none	standard	["bottom_row.3", "bottom_row.8"]	\N	\N	\N	\N	\N	\N
428877e7-6bd0-4b9e-810a-e926a1abcb95	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	bottom_space_d	14	Desert city skyline silhouetted at twilight.	f	none	standard	["bottom_row.9"]	\N	\N	\N	\N	\N	\N
7011e3f6-f838-40b8-ab2d-5281510d4b03	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	bottom_battle	15	Ancient warrior in armor, ready for battle.	f	none	standard	["bottom_row.7"]	\N	\N	\N	\N	\N	\N
90740bfa-9cb0-45c9-b1c1-4ee5d643b8b2	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	side_property	16	Sand-swept pathways winding past aged ruins.	f	none	standard	["left_col.0", "left_col.1", "left_col.3", "left_col.4", "right_col.1", "right_col.2", "right_col.3"]	\N	\N	\N	\N	\N	\N
f5f973ce-82ef-4e50-a3e4-f926f6590f76	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	side_battle	17	Epic sword duel, dynamic and intense.	f	none	standard	["left_col.2", "right_col.0", "right_col.4"]	\N	\N	\N	\N	\N	\N
edd80ef5-4cd7-49b4-997b-850725bab7eb	02ad5018-b82e-49ce-ad23-43d20ff06c9d	space	top_battle	18	Warrior atop a rearing horse, defiant stance.	f	none	standard	["top_row.3"]	\N	\N	\N	\N	\N	\N
b46f8f7d-4be4-4039-a74d-3d6c18f417fb	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	corner_tl	0		f	none	standard	["top_row.0"]	\N	\N	\N	\N	\N	\N
4b1b3c50-561a-4a83-bf2d-1f82ff63cf64	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	corner_tr	1		f	none	standard	["top_row.11"]	\N	\N	\N	\N	\N	\N
8c059f13-0c61-485e-a588-ec606a267937	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	corner_bl	2		f	none	standard	["bottom_row.0"]	\N	\N	\N	\N	\N	\N
68c5291f-eee0-4465-8e3a-41e636391c0f	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	corner_br	3		f	none	standard	["bottom_row.11"]	\N	\N	\N	\N	\N	\N
aea8956c-4548-4824-a55b-f37d0885e027	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	top_banner_a	4		f	none	standard	["top_row.5"]	\N	\N	\N	\N	\N	\N
2eb50420-6ef1-4114-8f77-2e20353f7949	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	top_banner_b	5		f	none	standard	["top_row.7"]	\N	\N	\N	\N	\N	\N
9fa68c42-09da-4f2c-b249-f0b5ffadaeb6	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	top_space_a	6		f	none	standard	["top_row.1", "top_row.4", "top_row.8"]	\N	\N	\N	\N	\N	\N
f781123b-b8c3-4cb9-93e9-a220b4c7a79a	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	top_space_b	7		f	none	standard	["top_row.2", "top_row.6", "top_row.9"]	\N	\N	\N	\N	\N	\N
a23b8bc0-fd75-4664-8a7f-b8eda64d8d13	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	top_space_c	8		f	none	standard	["top_row.3", "top_row.10"]	\N	\N	\N	\N	\N	\N
fdf3cf7e-d33f-41aa-9695-b06216bf4cb6	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	bottom_banner_a	9		f	none	standard	["bottom_row.5"]	\N	\N	\N	\N	\N	\N
81741217-4816-444e-bd2e-2b1098297118	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	bottom_banner_b	10		f	none	standard	["bottom_row.6"]	\N	\N	\N	\N	\N	\N
a9ed473b-2d13-41a2-9910-4522f57e82e3	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	bottom_space_a	11		f	none	standard	["bottom_row.1", "bottom_row.4"]	\N	\N	\N	\N	\N	\N
18e98814-2c39-4430-a959-8c588f6598f0	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	bottom_space_b	12		f	none	standard	["bottom_row.2", "bottom_row.10"]	\N	\N	\N	\N	\N	\N
4dcf9c1d-c379-4857-9696-77b3c7674993	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	bottom_space_c	13		f	none	standard	["bottom_row.3", "bottom_row.8"]	\N	\N	\N	\N	\N	\N
c4cf47c4-1d00-4629-9594-e07424b94046	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	bottom_space_d	14		f	none	standard	["bottom_row.9"]	\N	\N	\N	\N	\N	\N
81acf998-ba36-4063-9d87-515a8af42428	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	bottom_battle	15		f	none	standard	["bottom_row.7"]	\N	\N	\N	\N	\N	\N
5decb330-6524-46b3-8fb0-8afcc3c76fbc	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	side_property	16		f	none	standard	["left_col.0", "left_col.1", "left_col.3", "left_col.4", "right_col.1", "right_col.2", "right_col.3"]	\N	\N	\N	\N	\N	\N
247db5b4-dd39-44bb-a67d-2c48b9b5f23f	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	side_battle	17		f	none	standard	["left_col.2", "right_col.0", "right_col.4"]	\N	\N	\N	\N	\N	\N
4bcac0b7-2088-4ec1-9509-03db74d329ec	ed1456f7-12ef-48d3-ac59-4c93634c8a33	space	top_battle	18		f	none	standard	["top_row.3"]	\N	\N	\N	\N	\N	\N
3c8b63b3-f8a3-47a7-acea-be76a2c60b12	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	corner_tl	0	Cupcake with pink frosting and cherry	f	none	standard	["top_row.0"]	\N	\N	\N	\N	\N	\N
872ef89e-b657-4aa3-a111-ecfd53a28ad6	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	corner_tr	1	Chocolate truffle with golden wrapper	f	none	standard	["top_row.11"]	\N	\N	\N	\N	\N	\N
85aa67aa-e1a5-4791-b59b-b2acbbbc264e	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	corner_bl	2	Slice of fruit-topped cheesecake	f	none	event	["bottom_row.0"]	\N	\N	\N	\N	\N	\N
082877ca-ecfb-4a41-aa0d-cf563b0b5da3	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	corner_br	3	Caramel apple with candy sprinkles	f	none	standard	["bottom_row.11"]	\N	\N	\N	\N	\N	\N
d55dea7d-d53d-45c6-b6da-a692ae542065	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	top_banner_a	4	Mint green macaron illustration	f	none	standard	["top_row.5"]	\N	\N	\N	\N	\N	\N
0f4e58ce-6367-46db-a2a3-bff5fb9ed14c	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	top_banner_b	5	Stack of colorful donuts	f	none	standard	["top_row.7"]	\N	\N	\N	\N	\N	\N
3eb21e06-e33c-4a97-88b4-04c55309fbca	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	top_space_a	6	Slice of swiss roll cake	f	none	standard	["top_row.1", "top_row.4", "top_row.8"]	\N	\N	\N	\N	\N	\N
15908a34-82c3-4044-82f5-be891a18d2eb	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	top_space_b	7	Blueberry tart on a plate	f	none	standard	["top_row.2", "top_row.6", "top_row.9"]	\N	\N	\N	\N	\N	\N
d14b42cb-f4b1-4b0d-aeed-5c107ca6c915	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	top_space_c	8	Glazed donut with sprinkles	f	none	standard	["top_row.3", "top_row.10"]	\N	\N	\N	\N	\N	\N
d313c7b5-9929-4cda-9c93-a89e50dbaf2f	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	bottom_banner_a	9	Assorted cookies in a basket	f	none	standard	["bottom_row.5"]	\N	\N	\N	\N	\N	\N
6265da1c-009c-4cd4-b152-e1f66670471d	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	bottom_banner_b	10	Plate of assorted chocolates	f	none	standard	["bottom_row.6"]	\N	\N	\N	\N	\N	\N
08e47ed0-a9ec-492b-af8b-7594e773b73f	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	bottom_space_a	11	Chocolate eclair with cream	f	none	standard	["bottom_row.1", "bottom_row.4"]	\N	\N	\N	\N	\N	\N
e334954a-a8fb-40cb-ae6d-5f61740b55ab	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	bottom_space_b	12	Vanilla cupcake with sprinkles	f	none	standard	["bottom_row.2", "bottom_row.10"]	\N	\N	\N	\N	\N	\N
9f296306-f1f5-4cbb-a34b-7ab58fb695af	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	bottom_space_c	13	Slice of strawberry cake	f	none	standard	["bottom_row.3", "bottom_row.8"]	\N	\N	\N	\N	\N	\N
0f27144e-1bf7-4c17-a23e-dc53d2881d92	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	bottom_space_d	14	Tall glass of milkshake	f	none	event	["bottom_row.9"]	\N	\N	\N	\N	\N	\N
0598d0b9-b2a9-4b75-9748-271f7e455eb7	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	bottom_battle	15	Tower of pancakes with syrup	f	none	standard	["bottom_row.7"]	\N	\N	\N	\N	\N	\N
0b9f3635-5d2b-42b7-ad39-e1c63f6525cc	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	side_property	16	Macaron tower with icing	f	none	standard	["left_col.0", "left_col.1", "left_col.3", "left_col.4", "right_col.1", "right_col.2", "right_col.3"]	\N	\N	\N	\N	\N	\N
28c15232-e56e-4e43-ad03-b0867b84f00c	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	side_battle	17	Chocolate lava cake with spoon	f	none	standard	["left_col.2", "right_col.0", "right_col.4"]	\N	\N	\N	\N	\N	\N
7caa3c37-1794-49ca-9c65-cbe90c6d81df	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	space	top_battle	18	Plate of colorful cupcakes	f	none	standard	["top_row.3"]	\N	\N	\N	\N	\N	\N
e27dc48f-7afd-4e66-bc76-5c1c22e7ccd6	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	corner_tl	0		f	none	standard	["top_row.0"]	\N	\N	\N	\N	\N	\N
5157cd6d-20ba-483d-a9d3-039b22a24fb5	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	corner_tr	1		f	none	standard	["top_row.11"]	\N	\N	\N	\N	\N	\N
fbd9f23e-a376-4538-b63b-6f9b55c31682	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	corner_bl	2		f	none	standard	["bottom_row.0"]	\N	\N	\N	\N	\N	\N
cb3bd3d4-313f-46ba-8e77-7fcadeab01ab	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	corner_br	3		f	none	standard	["bottom_row.11"]	\N	\N	\N	\N	\N	\N
d91f4653-8aba-40dc-937f-4e056c3a83aa	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	top_banner_a	4		f	none	standard	["top_row.5"]	\N	\N	\N	\N	\N	\N
9758708c-d525-4c80-b79d-b7a750868e9f	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	top_banner_b	5		f	none	standard	["top_row.7"]	\N	\N	\N	\N	\N	\N
3d615df3-b677-4dae-ab0c-417216922dbe	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	top_space_a	6		f	none	standard	["top_row.1", "top_row.4", "top_row.8"]	\N	\N	\N	\N	\N	\N
fa00a178-57d9-4212-8493-d7e758fe1974	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	top_space_b	7		f	none	standard	["top_row.2", "top_row.6", "top_row.9"]	\N	\N	\N	\N	\N	\N
fb01b404-3e5b-4553-9a8c-56d259264dd5	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	top_space_c	8		f	none	standard	["top_row.3", "top_row.10"]	\N	\N	\N	\N	\N	\N
fccc1e56-df0b-41f4-808a-37cb68107ed4	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	bottom_banner_a	9		f	none	standard	["bottom_row.5"]	\N	\N	\N	\N	\N	\N
fa0204f1-2560-4279-98f2-1cb7bc4446f1	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	bottom_banner_b	10		f	none	standard	["bottom_row.6"]	\N	\N	\N	\N	\N	\N
266e27ea-2057-4a93-a461-859cd2f5c9d3	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	bottom_space_a	11		f	none	standard	["bottom_row.1", "bottom_row.4"]	\N	\N	\N	\N	\N	\N
2047dfdf-f45e-4e46-9450-b7bb4d49d3e4	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	bottom_space_b	12		f	none	standard	["bottom_row.2", "bottom_row.10"]	\N	\N	\N	\N	\N	\N
066d36ef-cd5e-44c2-a05e-9b36de16850c	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	bottom_space_c	13		f	none	standard	["bottom_row.3", "bottom_row.8"]	\N	\N	\N	\N	\N	\N
c0b54677-1cbe-47b5-a831-aa6178b70e17	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	bottom_space_d	14		f	none	standard	["bottom_row.9"]	\N	\N	\N	\N	\N	\N
8d17cab5-340f-42e9-82a5-09e9c2f0b9cb	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	bottom_battle	15		f	none	standard	["bottom_row.7"]	\N	\N	\N	\N	\N	\N
3a043190-ff63-49cc-bacd-6d93af4e98ca	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	side_property	16		f	none	standard	["left_col.0", "left_col.1", "left_col.3", "left_col.4", "right_col.1", "right_col.2", "right_col.3"]	\N	\N	\N	\N	\N	\N
00dab7ae-4800-4a99-9e1b-e543519547cf	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	side_battle	17		f	none	standard	["left_col.2", "right_col.0", "right_col.4"]	\N	\N	\N	\N	\N	\N
c29fd3fc-4fe8-4a8d-81c2-4d8f7200f006	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	space	top_battle	18		f	none	standard	["top_row.3"]	\N	\N	\N	\N	\N	\N
a749dcf5-a4a4-43bd-b3d5-9e2e15a8b46c	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	corner_tl	0	Golden compass with intricate details.	f	none	standard	["top_row.0"]	\N	\N	\N	\N	\N	\N
bfa2a077-db5c-49d1-a2c5-a64568b61360	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	corner_tr	1	Ancient stone tower on cliff.	f	none	standard	["top_row.11"]	\N	\N	\N	\N	\N	\N
59e62e44-d8d2-4ec9-9934-de0f8c24c67b	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	corner_bl	2	Cloudy mountain path with snow.	f	none	standard	["bottom_row.0"]	\N	\N	\N	\N	\N	\N
bd020913-ed31-447c-b244-8c7af31636d7	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	corner_br	3	Mystical green vortex swirling.	f	none	standard	["bottom_row.11"]	\N	\N	\N	\N	\N	\N
24f13c30-f732-4347-8850-b1d6e5a2437a	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	top_banner_a	4	Shield with crossed swords emblem.	f	none	standard	["top_row.5"]	\N	\N	\N	\N	\N	\N
968f615f-0e99-4668-90c7-bdcf88cc96c2	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	top_banner_b	5	Golden crown on velvet pillow.	f	none	standard	["top_row.7"]	\N	\N	\N	\N	\N	\N
59bcc8ea-bd2d-44d2-8524-22f37d4b64d3	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	top_space_a	6	Rustic wooden bridge over stream.	f	none	standard	["top_row.1", "top_row.4", "top_row.8"]	\N	\N	\N	\N	\N	\N
99bbab32-f70e-4c12-8006-546a3005c110	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	top_space_b	7	Sunny meadow with colorful flowers.	f	none	standard	["top_row.2", "top_row.6", "top_row.9"]	\N	\N	\N	\N	\N	\N
abb2c968-e28d-4c62-bd53-e98649634751	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	top_space_c	8	Quaint village market scene.	f	none	standard	["top_row.3", "top_row.10"]	\N	\N	\N	\N	\N	\N
708d4ed0-6d3f-44ff-bf84-0adb6eb8cc78	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	bottom_banner_a	9	Heated blacksmith forge glowing.	f	none	standard	["bottom_row.5"]	\N	\N	\N	\N	\N	\N
8fbd8393-6f29-4f81-ba7f-145a14e16e5c	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	bottom_banner_b	10	Ornate treasure chest with gems.	f	none	standard	["bottom_row.6"]	\N	\N	\N	\N	\N	\N
478f8d5d-651d-46bd-bcc8-617f86fb2b01	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	bottom_space_a	11	Winding forest path lined with trees.	f	none	standard	["bottom_row.1", "bottom_row.4"]	\N	\N	\N	\N	\N	\N
b5df41df-039b-4297-a8cc-dd99a81c48f4	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	bottom_space_b	12	Lush field with windmill spinning.	f	none	standard	["bottom_row.2", "bottom_row.10"]	\N	\N	\N	\N	\N	\N
c7a152cd-ead5-4b93-b94c-ab0cd13b9130	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	bottom_space_c	13	Path leading into an ancient cave.	f	none	standard	["bottom_row.3", "bottom_row.8"]	\N	\N	\N	\N	\N	\N
fd0f27d6-bc33-43fe-940a-a2570f175e8d	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	bottom_space_d	14	Knight's training ground with armor.	f	none	standard	["bottom_row.9"]	\N	\N	\N	\N	\N	\N
efc92614-877d-451b-8eb7-721b227cb010	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	bottom_battle	15	Circular arena with wooden spikes.	f	none	standard	["bottom_row.7"]	\N	\N	\N	\N	\N	\N
2144c7b3-d901-4db9-8b3a-d67463c6f4c0	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	side_property	16	Serene countryside path with fence.	f	none	standard	["left_col.0", "left_col.1", "left_col.3", "left_col.4", "right_col.1", "right_col.2", "right_col.3"]	\N	\N	\N	\N	\N	\N
b5d2070d-0f7c-4a34-8c26-ade28f2d3dc6	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	side_battle	17	War-torn battlefield with smoke.	f	none	standard	["left_col.2", "right_col.0", "right_col.4"]	\N	\N	\N	\N	\N	\N
8bdc06ef-b5e1-4b68-bc9f-98a6fa7ebe12	ef5082cd-a41e-4319-9b9d-1f42842a518c	space	top_battle	18	Path through vibrant purple cave.	f	none	standard	["top_row.3"]	\N	\N	\N	\N	\N	\N
2eaaf833-8981-4907-b485-ae449bc17302	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	corner_tl	0		f	none	standard	["top_row.0"]	\N	\N	\N	\N	\N	\N
2d0890b4-7dc8-423e-b2c5-ea7a9cd62c07	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	corner_tr	1		f	none	standard	["top_row.11"]	\N	\N	\N	\N	\N	\N
44e93a32-97ef-41b9-9136-cdfcf844e9b8	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	corner_bl	2		f	none	standard	["bottom_row.0"]	\N	\N	\N	\N	\N	\N
a90d2028-91b7-4be9-bb27-770963495934	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	corner_br	3		f	none	standard	["bottom_row.11"]	\N	\N	\N	\N	\N	\N
17c553a7-cae3-4299-a450-43143bee6120	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	top_banner_a	4		f	none	standard	["top_row.5"]	\N	\N	\N	\N	\N	\N
1c424f14-ee0d-4d21-8a0d-577690598a9e	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	top_banner_b	5		f	none	standard	["top_row.7"]	\N	\N	\N	\N	\N	\N
cd53736c-a867-46ce-a27d-43f77d0815c9	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	top_space_a	6		f	none	standard	["top_row.1", "top_row.4", "top_row.8"]	\N	\N	\N	\N	\N	\N
89cd5b76-0391-4944-976c-be55ef4d3b63	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	top_space_b	7		f	none	standard	["top_row.2", "top_row.6", "top_row.9"]	\N	\N	\N	\N	\N	\N
f36ffe13-29a8-4372-9c44-1cc36f37ee4e	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	top_space_c	8		f	none	standard	["top_row.3", "top_row.10"]	\N	\N	\N	\N	\N	\N
261d52cf-6be9-4304-9a83-74eb79c514ee	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	bottom_banner_a	9		f	none	standard	["bottom_row.5"]	\N	\N	\N	\N	\N	\N
1099e547-920a-4cee-99b6-38275c1b6bd9	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	bottom_banner_b	10		f	none	standard	["bottom_row.6"]	\N	\N	\N	\N	\N	\N
da2a02d0-0914-4d1d-8f60-10de47a2376b	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	bottom_space_a	11		f	none	standard	["bottom_row.1", "bottom_row.4"]	\N	\N	\N	\N	\N	\N
419331a8-b728-4de7-bffc-43820f8f297f	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	bottom_space_b	12		f	none	standard	["bottom_row.2", "bottom_row.10"]	\N	\N	\N	\N	\N	\N
3780c51d-a936-44da-8e10-9cea7ec29e4f	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	bottom_space_c	13		f	none	standard	["bottom_row.3", "bottom_row.8"]	\N	\N	\N	\N	\N	\N
e0164400-aaca-4211-9d0e-9ca8d5f63b14	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	bottom_space_d	14		f	none	standard	["bottom_row.9"]	\N	\N	\N	\N	\N	\N
76725502-2f93-47d3-8395-b4b5868c15d4	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	bottom_battle	15		f	none	standard	["bottom_row.7"]	\N	\N	\N	\N	\N	\N
2dd4a689-ed8f-46ac-9243-90414b55c402	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	side_property	16		f	none	standard	["left_col.0", "left_col.1", "left_col.3", "left_col.4", "right_col.1", "right_col.2", "right_col.3"]	\N	\N	\N	\N	\N	\N
28dab9bb-3bbf-49b0-87cc-09add631d8f3	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	side_battle	17		f	none	standard	["left_col.2", "right_col.0", "right_col.4"]	\N	\N	\N	\N	\N	\N
1a5b4a63-4090-4c0f-889a-79530dfd9dca	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	space	top_battle	18		f	none	standard	["top_row.3"]	\N	\N	\N	\N	\N	\N
b758f927-d251-4f7c-bdaf-fb6080466439	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_left_top	0		f	none	\N	\N	180	180	440	420	260	240
83b63641-ebf1-429c-ac2c-24ace723bc4a	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_left_mid	1		f	none	\N	\N	180	420	440	660	260	240
4ca2d6df-3011-4842-a71d-90a71bd65690	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_left_bot	2		f	none	\N	\N	180	660	440	900	260	240
4ce101b9-6fc8-40cb-b2a7-2a94d8980818	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_cleft_top	3		f	none	\N	\N	440	180	700	420	260	240
2647431b-4f27-4a7f-96bc-01fe7ea41442	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_cleft_mid	4		f	none	\N	\N	440	420	700	660	260	240
4a7df3a7-b835-4a3a-8d42-79de82de0975	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_cleft_bot	5		f	none	\N	\N	440	660	700	900	260	240
b1404ae2-5a58-4988-987e-5677ee351817	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_cright_top	6		f	none	\N	\N	1220	180	1480	420	260	240
23b63856-2d47-41e8-9c85-e410b22d42d0	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_cright_mid	7		f	none	\N	\N	1220	420	1480	660	260	240
d5b90dae-33ca-49d1-a558-cd15e670f1b6	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_cright_bot	8		f	none	\N	\N	1220	660	1480	900	260	240
da32cea7-87ee-49bc-98f9-ab5b044934df	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_right_top	9		f	none	\N	\N	1480	180	1740	420	260	240
efdc4968-90f2-4018-a66a-f83c42c7da41	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_right_mid	10		f	none	\N	\N	1480	420	1740	660	260	240
db3b7b81-e6c8-4976-b928-8cd828f6c038	748e880d-ceab-46e3-96f8-7684903a2727	panel	panel_right_bot	11		f	none	\N	\N	1480	660	1740	900	260	240
78a9118e-745a-4e25-8bc9-fa4a1209b830	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_left_top	0	Cactus cluster in arid landscape.	f	none	\N	\N	180	180	440	420	260	240
81113fda-b53a-40dc-890a-97b40b012779	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_left_mid	1	Scorpion surrounded by desert flora.	f	none	\N	\N	180	420	440	660	260	240
89e475cd-ccd7-4d29-aa83-6ae1e92c108a	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_left_bot	2	Glimpse of ancient city through palms.	f	none	\N	\N	180	660	440	900	260	240
50386fe4-100c-40a0-840f-c4e0a74682b4	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_cleft_top	3	Starry night over crescent dunes.	f	none	\N	\N	440	180	700	420	260	240
5d8890ed-f2b7-493a-ab1f-e35631c68858	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_cleft_mid	4	Desert horizon with radiant sunrise.	f	none	\N	\N	440	420	700	660	260	240
43813784-379b-451f-bf2c-e16c7856225d	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_cleft_bot	5	Lone traveler shaded by a rock.	f	none	\N	\N	440	660	700	900	260	240
2cbd6c27-c584-4d31-b176-40e1f5482c32	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_cright_top	6	Arabian stallion galloping, mane flowing.	f	none	\N	\N	1220	180	1480	420	260	240
f527602e-d48c-414c-8ab3-0575f7cf43cc	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_cright_mid	7	Parched desert with a distant mirage.	f	none	\N	\N	1220	420	1480	660	260	240
7d1e2f22-b398-4542-8d7b-d983a8524715	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_cright_bot	8	Mystic runes glowing on ancient stone.	f	none	\N	\N	1220	660	1480	900	260	240
b354290a-ef3d-452f-b9ff-a38cba89db8b	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_right_top	9	Silhouette of camels, distant dunes.	f	none	\N	\N	1480	180	1740	420	260	240
d6c3b0de-f700-46fb-b5ea-c5f2502aee0f	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_right_mid	10	Ornate lantern casting intricate shadows.	f	none	\N	\N	1480	420	1740	660	260	240
ad30df59-e3b2-45b8-820b-c9e70f58206c	02ad5018-b82e-49ce-ad23-43d20ff06c9d	panel	panel_right_bot	11	Crescent moon illuminating desert sands.	f	none	\N	\N	1480	660	1740	900	260	240
9901bc72-d5db-45e2-9d9e-7fecc14b302a	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_left_top	0		f	none	\N	\N	180	180	440	420	260	240
8fbfc195-3048-4ed6-82f0-d4deabc928f1	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_left_mid	1		f	none	\N	\N	180	420	440	660	260	240
123ce6f7-4169-443a-8c7a-95ffc7af4ad1	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_left_bot	2		f	none	\N	\N	180	660	440	900	260	240
f4a2f481-1e81-4596-9e23-fec263b4c18a	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_cleft_top	3		f	none	\N	\N	440	180	700	420	260	240
e4dbdfa2-c3e8-4d7b-9431-08e65201ef6f	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_cleft_mid	4		f	none	\N	\N	440	420	700	660	260	240
30dd1fa0-58e8-4cf7-abdd-adf07fbb4ca6	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_cleft_bot	5		f	none	\N	\N	440	660	700	900	260	240
620cc25b-2030-402d-b098-39669a5632b8	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_cright_top	6		f	none	\N	\N	1220	180	1480	420	260	240
c1895bf3-4d24-411e-be7a-6ee621030fea	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_cright_mid	7		f	none	\N	\N	1220	420	1480	660	260	240
dc67f0ff-2afe-469c-a1ff-83b9f66090f5	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_cright_bot	8		f	none	\N	\N	1220	660	1480	900	260	240
f50dc4cf-19cb-49c3-9291-df51a38eebec	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_right_top	9		f	none	\N	\N	1480	180	1740	420	260	240
27947c0e-4a0b-4b05-8930-9b6b580e2422	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_right_mid	10		f	none	\N	\N	1480	420	1740	660	260	240
f195516e-d8fe-4498-ba46-4b9a602a40cf	ed1456f7-12ef-48d3-ac59-4c93634c8a33	panel	panel_right_bot	11		f	none	\N	\N	1480	660	1740	900	260	240
460f79ce-307f-49a5-a4a5-1209579ead34	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_left_top	0	Set of pastel-colored cake icons	f	none	\N	\N	180	180	440	420	260	240
67a2a34e-190d-4f02-a222-20e1505d18c2	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_left_mid	1	Five lavender cupcake silhouettes	f	none	\N	\N	180	420	440	660	260	240
2de6df2f-d711-4994-a76e-6b0de1241c10	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_left_bot	2	Pink heart shapes on a stripe	f	none	\N	\N	180	660	440	900	260	240
ce43169f-64c2-45d6-952c-6358b5cee856	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_cleft_top	3	Green star symbols in a row	f	none	\N	\N	440	180	700	420	260	240
dde185fd-bc66-45ca-83f0-6b846e12c8b3	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_cleft_mid	4	Three round pastry icons	f	none	\N	\N	440	420	700	660	260	240
7401a1e1-4a25-44e2-9f04-ed249ef0b08c	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_cleft_bot	5	Cakes on stands; purple background	f	none	\N	\N	440	660	700	900	260	240
2888765c-8054-4a54-83c4-551eccb8a741	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_cright_top	6	Series of outlined cake shapes	f	none	\N	\N	1220	180	1480	420	260	240
7aa5b745-48c6-440e-8b2a-c4c4f5d59443	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_cright_mid	7	Desserts with a berry topping	f	none	\N	\N	1220	420	1480	660	260	240
5f17228e-6a0b-494e-b633-281f40e5e39c	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_cright_bot	8	Transparent jar with candy swirls	f	none	\N	\N	1220	660	1480	900	260	240
90e7b5fd-b225-4070-a5a7-6ab0b2c20704	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_right_top	9	Trio of decorated cupcakes	f	none	\N	\N	1480	180	1740	420	260	240
1e0dc30f-c899-4c89-bd69-e95c31ff85b9	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_right_mid	10	Four circular treat emblems	f	none	\N	\N	1480	420	1740	660	260	240
7631057a-746e-4aea-ac4d-c2744399a38b	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	panel	panel_right_bot	11	Row of fruit-topped pastries	f	none	\N	\N	1480	660	1740	900	260	240
c22e04db-c3ac-43d0-8893-0ffaea743d52	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_left_top	0		f	none	\N	\N	180	180	440	420	260	240
7c89301b-4aac-4cee-87c8-7701363844fb	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_left_mid	1		f	none	\N	\N	180	420	440	660	260	240
3fae9fbc-a85c-439e-832e-90c6017cccf7	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_left_bot	2		f	none	\N	\N	180	660	440	900	260	240
32420415-f7aa-4306-9bb9-ca2ed0d7e9a3	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_cleft_top	3		f	none	\N	\N	440	180	700	420	260	240
a4804550-638b-4b04-a7ed-1320093f6021	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_cleft_mid	4		f	none	\N	\N	440	420	700	660	260	240
3e33b7af-60ee-43bd-9086-cb3199859bf9	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_cleft_bot	5		f	none	\N	\N	440	660	700	900	260	240
1860af04-66da-43a1-8abb-ab6c2c102129	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_cright_top	6		f	none	\N	\N	1220	180	1480	420	260	240
54c664d1-3779-47ce-b315-b90d2ab28db1	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_cright_mid	7		f	none	\N	\N	1220	420	1480	660	260	240
6247784c-2350-4afc-be07-28cacf9256b8	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_cright_bot	8		f	none	\N	\N	1220	660	1480	900	260	240
802ce82f-0f89-4b05-8641-b4116ffe6387	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_right_top	9		f	none	\N	\N	1480	180	1740	420	260	240
82ad9a10-48f2-47db-88d1-eefc6ed32dbf	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_right_mid	10		f	none	\N	\N	1480	420	1740	660	260	240
e0f973a9-5a5e-4ded-896a-c0d0635c26df	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	panel	panel_right_bot	11		f	none	\N	\N	1480	660	1740	900	260	240
c5c875e6-9d72-46c7-9edb-962298fba0a6	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_left_top	0	Misty enchanted forest with fairies.	f	none	\N	\N	180	180	440	420	260	240
01e711cd-c2c3-4664-be26-7779311c6ae0	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_left_mid	1	Stone path through ancient ruins.	f	none	\N	\N	180	420	440	660	260	240
8c7a32bb-d86d-466c-a7d8-ddb0ab923021	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_left_bot	2	Desert canyon with towering cliffs.	f	none	\N	\N	180	660	440	900	260	240
fcd48d2a-f280-4e23-ab19-a2becede633b	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_cleft_top	3	Fertile valley with crystal river.	f	none	\N	\N	440	180	700	420	260	240
97462309-ed19-49c8-9634-4b89d6b55279	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_cleft_mid	4	Sunset over golden wheat fields.	f	none	\N	\N	440	420	700	660	260	240
2af0dd75-0b72-4a58-974b-d74de3c65e86	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_cleft_bot	5	Mountain stone path with waterfall.	f	none	\N	\N	440	660	700	900	260	240
e6b7c247-6302-4858-9d0e-8c58946dcca2	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_cright_top	6	Twilight forest with glowing mushrooms.	f	none	\N	\N	1220	180	1480	420	260	240
1c6fd98d-794c-459f-a733-deb2b37068c0	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_cright_mid	7	Charming village under full moon.	f	none	\N	\N	1220	420	1480	660	260	240
3680a1e8-cec2-41a8-af7a-7e8dc4605f0f	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_cright_bot	8	Lava river flanked by molten rocks.	f	none	\N	\N	1220	660	1480	900	260	240
f6c55288-3e22-4247-804b-d60f54a8ea1b	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_right_top	9	Frozen tundra with glacial crevasse.	f	none	\N	\N	1480	180	1740	420	260	240
3fc4acf3-7185-4747-8669-98dc821f4b82	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_right_mid	10	Whispering woods with hidden paths.	f	none	\N	\N	1480	420	1740	660	260	240
3c59309b-930d-4fd2-9283-9635a9296f22	ef5082cd-a41e-4319-9b9d-1f42842a518c	panel	panel_right_bot	11	Lush meadow with grazing unicorns.	f	none	\N	\N	1480	660	1740	900	260	240
d1a6a710-3790-4e05-a73f-1133092cd4f0	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_left_top	0		f	none	\N	\N	180	180	440	420	260	240
323f382a-be8d-4647-b8e5-b6c215d33066	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_left_mid	1		f	none	\N	\N	180	420	440	660	260	240
f0d8a6da-37b1-4ad7-bfdc-f157aa560347	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_left_bot	2		f	none	\N	\N	180	660	440	900	260	240
206b99bf-12a5-40d4-bd06-29926392f199	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_cleft_top	3		f	none	\N	\N	440	180	700	420	260	240
0eaf7353-1122-4add-b79c-0a564145c7ed	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_cleft_mid	4		f	none	\N	\N	440	420	700	660	260	240
462e5776-0eea-46d5-be0b-93be9ef36b3e	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_cleft_bot	5		f	none	\N	\N	440	660	700	900	260	240
63c687ad-adfd-48db-a79f-05aa972bdd26	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_cright_top	6		f	none	\N	\N	1220	180	1480	420	260	240
b62b3167-d379-48d6-aaf5-e0e6413ea939	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_cright_mid	7		f	none	\N	\N	1220	420	1480	660	260	240
761d2f36-3d20-4f12-bb4c-74bd1578f9de	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_cright_bot	8		f	none	\N	\N	1220	660	1480	900	260	240
fcba00b3-51b1-4516-88d3-5211ae4ca818	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_right_top	9		f	none	\N	\N	1480	180	1740	420	260	240
2c257e72-bb8d-4ad3-9f0c-d8ee801984d4	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_right_mid	10		f	none	\N	\N	1480	420	1740	660	260	240
1d455159-e3c9-466e-acf7-07d6f484b8db	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	panel	panel_right_bot	11		f	none	\N	\N	1480	660	1740	900	260	240
94d43b6f-1c87-4889-b9ef-6f2d49599f43	748e880d-ceab-46e3-96f8-7684903a2727	centerpiece	centerpiece	0		f	none	\N	\N	700	180	1220	900	520	720
cc4b3614-a419-4f9a-bfe5-1624083ee0e3	02ad5018-b82e-49ce-ad23-43d20ff06c9d	centerpiece	centerpiece	0	Majestic palace by a river, surrounded by mountains.	f	none	\N	\N	700	180	1220	900	520	720
42e02b75-fce2-49d0-b195-fca2769dfc61	ed1456f7-12ef-48d3-ac59-4c93634c8a33	centerpiece	centerpiece	0		f	none	\N	\N	700	180	1220	900	520	720
89bf51b5-9e65-4488-986f-6332e0e40f11	2d5a1a6b-1a07-4b55-8ba3-373b15453bd3	centerpiece	centerpiece	0	Giant tiered cake in candyland landscape	f	none	\N	\N	700	180	1220	900	520	720
196ffcde-aab2-490a-a0d7-342650e454ab	e92c3dc7-ec23-4f36-9f78-ee04abf6106b	centerpiece	centerpiece	0		f	none	\N	\N	700	180	1220	900	520	720
340d35b6-5e84-4d0f-8f44-a120dd3fed4e	ef5082cd-a41e-4319-9b9d-1f42842a518c	centerpiece	centerpiece	0	Majestic crystal spire amidst enchanted landscape.	f	none	\N	\N	700	180	1220	900	520	720
315ad093-e4c7-459d-b98c-18a5dc094538	3de2757b-bbe2-4f74-9e36-d2e7d3285b48	centerpiece	centerpiece	0		f	none	\N	\N	700	180	1220	900	520	720
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
46c004b7a2a9482398aa262d103cf96e	admin@admin.com	$2b$12$heJK13dCZiAd838HM8DsL.XHvM0elqeVGuZwmafq7A6lvQEZ7jgOW	ben	✧	#902de1	1777514766934	1777932194502	admin
\.


--
-- Name: asset_versions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.asset_versions_id_seq', 15253, true);


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
-- Name: cells cells_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cells
    ADD CONSTRAINT cells_pkey PRIMARY KEY (id);


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
-- Name: cells uq_cells_board_kind_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cells
    ADD CONSTRAINT uq_cells_board_kind_slug UNIQUE (board_uuid, kind, slug);


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
-- Name: ix_asset_versions_cell_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_asset_versions_cell_id ON public.asset_versions USING btree (cell_id);


--
-- Name: ix_browser_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_browser_sessions_user_id ON public.browser_sessions USING btree (user_id);


--
-- Name: ix_cells_board_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cells_board_kind ON public.cells USING btree (board_uuid, kind);


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
-- Name: asset_versions asset_versions_cell_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.asset_versions
    ADD CONSTRAINT asset_versions_cell_id_fkey FOREIGN KEY (cell_id) REFERENCES public.cells(id) ON DELETE CASCADE;


--
-- Name: browser_sessions browser_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.browser_sessions
    ADD CONSTRAINT browser_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: cells cells_board_uuid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cells
    ADD CONSTRAINT cells_board_uuid_fkey FOREIGN KEY (board_uuid) REFERENCES public.board_games(id) ON DELETE CASCADE;


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

\unrestrict xvrjOOxc8L1Wj8vax7eaC3cr4E68LqhWRZsrFizfeM9SqJZ57gLOK7OcgsXSVz8

