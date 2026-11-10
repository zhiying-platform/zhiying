-- 迁移 002：chunks 补全文检索列（V0.2 S10）
-- 背景：schema_v1 冻结时遗漏 tsv，全文检索（FR-202）需要 jieba 分词后的 tsvector。
-- 幂等：可重复执行。

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv tsvector;

-- 中文分词在应用侧（jieba）完成，此处只建 GIN 索引
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING gin (tsv);
