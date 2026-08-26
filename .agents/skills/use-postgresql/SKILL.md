---
name: use-postgresql
description: how to connect and query a PostgreSQL database using psycopg
license: Apache 2.0
---

To use PostgreSQL in an endpoint, first use the tool `add-postgresql` to add the connection to your endpoint. This makes `ctx.POSTGRESQL` available as a `psycopg` connection.

## Running a query

Use `ctx.POSTGRESQL` to get the connection, then create a cursor and execute SQL:

```python
def query_table(args, ctx=None):
    conn = ctx.POSTGRESQL
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM my_table")
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        result = [dict(zip(columns, row)) for row in rows]
        return result
    finally:
        cur.close()
```

## INSERT, UPDATE, DELETE

For write operations, remember to commit and check the affected row count:

```python
def insert_row(args, ctx=None):
    conn = ctx.POSTGRESQL
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO my_table (name) VALUES (%s)", (args.get("name"),))
        conn.commit()
        return f"affected rows: {cur.rowcount}"
    finally:
        cur.close()
```

## CREATE TABLE

```python
def create_table(args, ctx=None):
    conn = ctx.POSTGRESQL
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS my_table (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255)
            )
        """)
        conn.commit()
        return cur.statusmessage
    finally:
        cur.close()
```

## Listing tables

To list all user tables in the database:

```python
cur.execute("""
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_type = 'BASE TABLE'
    AND table_schema NOT IN ('pg_catalog', 'information_schema')
""")
```

## Executing multiple statements

To run multiple SQL statements separated by newlines:

```python
def run_multi(conn, statements):
    cur = conn.cursor()
    try:
        for sql in statements:
            cur.execute(sql)
            conn.commit()
        return f"executed {len(statements)} statements"
    finally:
        cur.close()
```

## Rendering results as HTML

To return query results as an HTML table (useful when the action is called from a browser):

```python
def to_html(columns, rows):
    html = '<table border="1"><thead><tr>'
    html += ''.join(f'<th>{col}</th>' for col in columns)
    html += '</tr></thead><tbody>'
    for row in rows:
        html += '<tr>'
        html += ''.join(f'<td>{row[col]}</td>' for col in columns)
        html += '</tr>'
    html += '</tbody></table>'
    return {"output": f"found {len(rows)} rows", "html": html}
```
