CREATE TABLE "entries" ("id" INTEGER PRIMARY KEY, "code" TEXT NOT NULL, "quantity" INTEGER NOT NULL, "note" TEXT, "occurred_at" TEXT NOT NULL) STRICT;
CREATE UNIQUE INDEX "ux_entries_code" ON "entries" ("code");
