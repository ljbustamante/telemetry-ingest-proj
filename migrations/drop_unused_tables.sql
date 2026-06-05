-- Drop unused tables (no references in code, 0 rows)
-- Order: partitions first, then parent tables

-- readings_disk
DROP TABLE IF EXISTS readings_disk_2025_10;
DROP TABLE IF EXISTS readings_disk_parent_2025_11;
DROP TABLE IF EXISTS readings_disk_parent_2025_12;
DROP TABLE IF EXISTS readings_disk_parent;

-- readings_events
DROP TABLE IF EXISTS readings_events_2025_10;
DROP TABLE IF EXISTS readings_events_parent_2025_11;
DROP TABLE IF EXISTS readings_events_parent_2025_12;
DROP TABLE IF EXISTS readings_events_parent;

-- readings_gpu
DROP TABLE IF EXISTS readings_gpu_2025_10;
DROP TABLE IF EXISTS readings_gpu_parent_2025_11;
DROP TABLE IF EXISTS readings_gpu_parent_2025_12;
DROP TABLE IF EXISTS readings_gpu_parent;

-- readings_io_summary
DROP TABLE IF EXISTS readings_io_2025_10;
DROP TABLE IF EXISTS readings_io_summary_parent_2025_11;
DROP TABLE IF EXISTS readings_io_summary_parent_2025_12;
DROP TABLE IF EXISTS readings_io_summary_parent;

-- standalone
DROP TABLE IF EXISTS maint_actions;
