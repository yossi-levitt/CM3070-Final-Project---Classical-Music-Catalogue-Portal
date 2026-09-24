PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS composer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    birth_year INTEGER,
    death_year INTEGER,
    UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS work (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    composer_id INTEGER NOT NULL REFERENCES composer(id),
    catalogue_number TEXT,
    title TEXT NOT NULL,
    subtitle TEXT,
    genre TEXT,
    key_signature TEXT,
    year_composed INTEGER,
    year_completed INTEGER,
    dedication TEXT,
    notes TEXT,
    encoding_style TEXT,
    source_file TEXT,
    -- Count of <note> elements found under <music> in the source file (summed
    -- across movements for a multi-file work). Used to decide whether a
    -- notation preview is worth offering at all - a "hybrid" file can carry
    -- only a handful of illustrative notes, not a real playable score.
    note_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (composer_id, catalogue_number)
);

CREATE TABLE IF NOT EXISTS movement (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    title TEXT,
    tempo TEXT,
    key_signature TEXT,
    -- The opening words or musical incipit text for this movement, from
    -- <incip><incipText><p>, when the source encodes one. Only the first
    -- <p> found is kept, so a movement with several language variants only
    -- gets one of them.
    incipit TEXT,
    -- Set only for a movement ingested from its own separate MEI file
    -- (a multi-file work, e.g. one opera encoded as one file per movement);
    -- NULL for a movement extracted from within its work's own source file.
    source_file TEXT
);

CREATE TABLE IF NOT EXISTS instrument (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    UNIQUE (name)
);

CREATE TABLE IF NOT EXISTS work_instrument (
    work_id INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    instrument_id INTEGER NOT NULL REFERENCES instrument(id),
    count INTEGER,
    PRIMARY KEY (work_id, instrument_id)
);

CREATE TABLE IF NOT EXISTS manuscript (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    repository TEXT,
    shelf_mark TEXT,
    description TEXT,
    date_text TEXT
);

CREATE TABLE IF NOT EXISTS performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL REFERENCES work(id) ON DELETE CASCADE,
    performance_date TEXT,
    venue TEXT,
    city TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_work_composer ON work(composer_id);
CREATE INDEX IF NOT EXISTS idx_work_title ON work(title);
CREATE INDEX IF NOT EXISTS idx_work_catalogue ON work(catalogue_number);
CREATE INDEX IF NOT EXISTS idx_movement_work ON movement(work_id);
CREATE INDEX IF NOT EXISTS idx_manuscript_work ON manuscript(work_id);
CREATE INDEX IF NOT EXISTS idx_performance_work ON performance(work_id);
