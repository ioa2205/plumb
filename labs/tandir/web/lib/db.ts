import "server-only";

import { existsSync } from "node:fs";
import path from "node:path";
import { DatabaseSync, type SQLInputValue } from "node:sqlite";

// The web lab shares the API lab's SQLite database (and its sessions).
export function databaseFile(): string {
  const dataDir = process.env.TANDIR_DATA_DIR ?? path.resolve(process.cwd(), "../api/var");
  return path.join(dataDir, "tandir.db");
}

let connection: { file: string; db: DatabaseSync } | undefined;

export function db(): DatabaseSync {
  const file = databaseFile();
  if (connection?.file !== file) {
    if (!existsSync(file)) {
      throw new Error(
        `No lab database at ${file}. Seed it first: uv run python -m tandir --seed-only (in labs/tandir/api).`,
      );
    }
    connection?.db.close();
    const database = new DatabaseSync(file);
    database.exec("PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 2000;");
    connection = { file, db: database };
  }
  return connection.db;
}

export function closeDb(): void {
  connection?.db.close();
  connection = undefined;
}

export function one<T>(sql: string, ...params: SQLInputValue[]): T | undefined {
  return db().prepare(sql).get(...params) as T | undefined;
}

export function all<T>(sql: string, ...params: SQLInputValue[]): T[] {
  return db().prepare(sql).all(...params) as T[];
}

export function run(sql: string, ...params: SQLInputValue[]): number {
  return Number(db().prepare(sql).run(...params).changes);
}
