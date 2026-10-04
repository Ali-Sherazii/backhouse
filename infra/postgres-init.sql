-- Runs once, on the first start of the postgres container (empty data dir).
-- Passwords come from the container environment via psql's \getenv.

\getenv backhouse_pw BACKHOUSE_DB_PASSWORD
\getenv n8n_pw N8N_DB_PASSWORD
\getenv odoo_pw ODOO_DB_PASSWORD
\getenv langfuse_pw LANGFUSE_DB_PASSWORD

CREATE ROLE backhouse LOGIN PASSWORD :'backhouse_pw';
CREATE ROLE n8n LOGIN PASSWORD :'n8n_pw';
-- Odoo refuses to run as a superuser and needs CREATEDB for its database manager.
CREATE ROLE odoo LOGIN CREATEDB PASSWORD :'odoo_pw';
CREATE ROLE langfuse LOGIN PASSWORD :'langfuse_pw';

CREATE DATABASE backhouse OWNER backhouse;
CREATE DATABASE n8n OWNER n8n;
CREATE DATABASE odoo OWNER odoo ENCODING 'UTF8' TEMPLATE template0;
CREATE DATABASE langfuse OWNER langfuse;
