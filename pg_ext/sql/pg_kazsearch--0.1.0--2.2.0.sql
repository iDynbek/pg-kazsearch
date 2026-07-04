-- Upgrade pg_kazsearch 0.1.0 -> 2.2.0
--
-- 0.1.0 installs only mapped word-class tokens, so numbers, URLs and emails
-- were dropped from every tsvector. 2.2.0 adds `simple` mappings for them.
-- The template/dictionary/configuration objects are otherwise unchanged
-- (stemmer behavior lives in the shared library, which is replaced on
-- upgrade).
--
-- NOTE: tsvectors built before this upgrade do not contain numeric/url
-- tokens; regenerate stored/generated tsvector columns to pick them up.

-- Idempotent: dev builds of "0.1.0" from newer sources may already carry
-- these mappings, and ADD MAPPING has no IF NOT EXISTS.
ALTER TEXT SEARCH CONFIGURATION kazakh_cfg
    DROP MAPPING IF EXISTS FOR numword, numhword, hword_numpart,
                                int, uint, float, sfloat, version,
                                email, url, url_path, host, file;

ALTER TEXT SEARCH CONFIGURATION kazakh_cfg
    ADD MAPPING FOR numword, numhword, hword_numpart,
                    int, uint, float, sfloat, version,
                    email, url, url_path, host, file
    WITH simple;
