
        CREATE TABLE IF NOT EXISTS copilot_settings (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS copilot_meta (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS copilot_lessons (
            lesson_no INTEGER PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS copilot_learning_records (
            lesson_no INTEGER PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS copilot_drafts (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS copilot_generation_attempts (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS copilot_operations (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS learning_plans (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS learning_plan_versions (
            plan_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (plan_id, version)
        )
    ;

        CREATE TABLE IF NOT EXISTS learning_lessons (
            plan_id TEXT NOT NULL,
            lesson_no INTEGER NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (plan_id, lesson_no)
        )
    ;

        CREATE TABLE IF NOT EXISTS learning_drafts (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS learning_ai_attempts (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS learning_feedback (
            plan_id TEXT NOT NULL,
            lesson_no INTEGER NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (plan_id, lesson_no)
        )
    ;

        CREATE TABLE IF NOT EXISTS learning_publications (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS learning_draft_families (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS learning_settings (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS reading_records (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS reading_vocabulary (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS reading_reviews (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS reflection_entries (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS reflection_versions (
            entry_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (entry_id, version)
        )
    ;

        CREATE TABLE IF NOT EXISTS reflection_ai_attempts (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS reflection_operations (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS stock_records (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS error_records (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS error_types (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS prediction_records (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS behavior_applications (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS behavior_reports (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS knowledge_nodes (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    ;

        CREATE TABLE IF NOT EXISTS knowledge_links (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
