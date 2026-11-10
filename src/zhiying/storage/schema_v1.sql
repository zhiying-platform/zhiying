-- 知映 zhiying — 知识库表结构契约 V1（PRD §5.4 A2，DR-6 契约冻结于 V0.1/B6）
-- 目标库：zhiying；扩展：pgvector 0.8.3
-- 幂等：可重复执行；只建结构不写业务数据（入库逻辑属 V0.2 S8）

-- 扩展（需超级用户或已授权；幂等）
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- videos：视频级元数据与 A3 摘要挂载点
-- ============================================================
CREATE TABLE IF NOT EXISTS videos (
    id              TEXT PRIMARY KEY,                -- video_id（BV号/local-哈希）
    source_type     TEXT NOT NULL,                   -- bilibili|youtube|local|unknown
    source          TEXT NOT NULL,                   -- URL 或本地原路径
    title           TEXT NOT NULL DEFAULT '',
    uploader        TEXT NOT NULL DEFAULT '',
    duration        DOUBLE PRECISION NOT NULL DEFAULT 0,   -- 秒
    status          TEXT NOT NULL DEFAULT 'pending', -- pending|downloading|transcribing|visual|summarizing|done|failed
    language        TEXT NOT NULL DEFAULT 'zh',
    -- A3 结构化摘要（FR-107）
    summary_text    TEXT NOT NULL DEFAULT '',
    topics          TEXT[] NOT NULL DEFAULT '{}',
    -- 管道信息
    pipeline_version TEXT NOT NULL DEFAULT '',
    transcribe_origin TEXT NOT NULL DEFAULT '',     -- platform_subtitle|sensevoice|whisper_small
    vlm_provider    TEXT NOT NULL DEFAULT '',        -- siliconflow|longcat
    text_model      TEXT NOT NULL DEFAULT '',
    -- 观测（FR-304 雏形）
    cost_tokens     INTEGER NOT NULL DEFAULT 0,
    cost_files      JSONB NOT NULL DEFAULT '{}',     -- 各产物文件路径登记
    downloaded_at   TIMESTAMPTZ,
    processed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- segments：A1 多模态逐段落库（transcript.multimodal.jsonl 逐行）
-- ============================================================
CREATE TABLE IF NOT EXISTS segments (
    id           BIGSERIAL PRIMARY KEY,
    video_id     TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    seg_index    INTEGER NOT NULL,                   -- 段序号
    start_ts     DOUBLE PRECISION NOT NULL,
    end_ts       DOUBLE PRECISION NOT NULL,
    speech       TEXT NOT NULL DEFAULT '',
    speech_origin TEXT NOT NULL DEFAULT '',          -- platform_subtitle|sensevoice|whisper_*
    visual_facts TEXT[] NOT NULL DEFAULT '{}',       -- 命中帧的 VLM 描述
    screen_text  TEXT[] NOT NULL DEFAULT '{}',       -- OCR 抽取
    frame_refs   TEXT[] NOT NULL DEFAULT '{}',       -- 帧文件名（可回跳）
    UNIQUE (video_id, seg_index)
);
CREATE INDEX IF NOT EXISTS idx_segments_video ON segments(video_id);

-- ============================================================
-- chunks：检索单元（A2 核心，FR-202；回答引用最小粒度）
-- ============================================================
CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    video_id    TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    start_ts    DOUBLE PRECISION NOT NULL,           -- 合并窗口起点
    end_ts      DOUBLE PRECISION NOT NULL,           -- 合并窗口终点
    text        TEXT NOT NULL,                       -- 合并后文本（口播+画面要点）
    modality    TEXT NOT NULL DEFAULT 'mixed',       -- speech|visual|mixed
    embedding   vector(1024),                        -- BAAI/bge-m3 实测 1024 维；V0.2 填充
    tsv         tsvector,                            -- 全文检索（应用侧 jieba 分词后写入）
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (video_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_video ON chunks(video_id);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING gin (tsv);
-- 向量索引：V0.2 数据填充后按规模选 HNSW/IVFFlat，此处先留普通索引位
-- CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);

-- ============================================================
-- updated_at 触发器（videos）
-- ============================================================
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_videos_touch ON videos;
CREATE TRIGGER trg_videos_touch
    BEFORE UPDATE ON videos
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
