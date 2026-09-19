CREATE TABLE "users" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "email" TEXT NOT NULL, "nickname" TEXT, "status" TEXT NOT NULL) STRICT;

CREATE UNIQUE INDEX "ux_users_email" ON "users" ("email");

CREATE TABLE "profiles" ("user_id" INTEGER PRIMARY KEY, "bio" TEXT, FOREIGN KEY ("user_id") REFERENCES "users" ("id") ON DELETE CASCADE) STRICT;

CREATE TABLE "teams" ("id" INTEGER PRIMARY KEY AUTOINCREMENT, "name" TEXT NOT NULL) STRICT;

CREATE UNIQUE INDEX "ux_teams_name" ON "teams" ("name");

CREATE TABLE "memberships" ("team_id" INTEGER NOT NULL, "user_id" INTEGER NOT NULL, "alias" TEXT NOT NULL, PRIMARY KEY ("team_id", "user_id"), FOREIGN KEY ("team_id") REFERENCES "teams" ("id") ON DELETE CASCADE, FOREIGN KEY ("user_id") REFERENCES "users" ("id") ON DELETE RESTRICT) STRICT;

CREATE UNIQUE INDEX "ux_memberships_team_id_alias" ON "memberships" ("team_id", "alias");

CREATE INDEX "ix_memberships_user_id" ON "memberships" ("user_id");
