-- 迁移 003：videos 补内容哈希（上传去重，2026-11-10）
-- 背景：本地上传的 video_id 由「文件名+大小」生成，同名重复上传加时间戳后缀后
-- 生成新 ID，导致同一视频重复处理。content_hash 为文件级 SHA256，内容级去重。
-- 幂等：可重复执行。

ALTER TABLE videos ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_videos_content_hash ON videos (content_hash);
