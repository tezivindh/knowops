-- Create test database for isolated testing
-- This runs automatically when PostgreSQL container starts

SELECT 'CREATE DATABASE knowops_test'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'knowops_test')\gexec

GRANT ALL PRIVILEGES ON DATABASE knowops_test TO knowops;
