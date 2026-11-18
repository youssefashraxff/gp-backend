--Concepts table

CREATE TABLE public.concepts (
    id            TEXT PRIMARY KEY,
    input         JSONB NOT NULL,
    status        TEXT NOT NULL DEFAULT 'created' CHECK (
                      status IN ('created', 'in_progress', 'awaiting_approval', 'completed', 'failed')
                  ),
    current_phase TEXT NOT NULL DEFAULT 'research' CHECK (
                      current_phase IN ('research', 'brand_design', 'visuals', 'investment')
                  ),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE FUNCTION public.set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_concepts_updated_at
BEFORE UPDATE ON public.concepts
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- 2. phase_results table
CREATE TABLE public.phase_results (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id  TEXT NOT NULL REFERENCES public.concepts(id) ON DELETE CASCADE,
    phase       TEXT NOT NULL CHECK (
                    phase IN ('research', 'brand_design', 'visuals', 'investment')
                ),
    version     INTEGER NOT NULL CHECK (version >= 1),
    status      TEXT NOT NULL CHECK (
                    status IN ('queued', 'running', 'waiting_for_expert', 'awaiting_approval', 'done', 'stale', 'failed')
                ),
    built_from  JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(built_from) = 'array'),
    fields      JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(fields) = 'object'),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_phase_results_concept_phase_version UNIQUE (concept_id, phase, version)
);

ALTER TABLE public.concepts      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.phase_results ENABLE ROW LEVEL SECURITY;