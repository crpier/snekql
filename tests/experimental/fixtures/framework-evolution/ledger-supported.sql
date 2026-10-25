BEGIN TRANSACTION;
CREATE TABLE "accounts" ("id" INTEGER PRIMARY KEY, "is_admin" INTEGER NOT NULL) STRICT;
INSERT INTO "accounts" VALUES(1,1);
INSERT INTO "accounts" VALUES(2,0);
CREATE TABLE `snekql_experimental_migrations` (digest TEXT PRIMARY KEY, revision TEXT NOT NULL, predecessor TEXT, phase TEXT NOT NULL, catalog TEXT NOT NULL, acknowledged INTEGER NOT NULL, total INTEGER NOT NULL, state TEXT NOT NULL, plan TEXT NOT NULL, observation TEXT NOT NULL, reconciliations TEXT NOT NULL) STRICT;
INSERT INTO "snekql_experimental_migrations" VALUES('1a63e1c9fd6b589be10c4a78c2a39f8daea38d0b172978fe0276eb438be847b6','001_accounts',NULL,'complete','cce76e862f0e4cb1ddb54870906491460fe59d0aea9852086ad5b29883c55d3c',1,1,'dc0064f16ac949df84959a0a65e9bad514f6b2c46121bfa6cceecaa21c2f0b98','bc7dd10f6a28de35e58bee8e6b719e7bfda7efbb20df2ee9507736e646a22f2f','{"catalog":[["table","accounts","accounts","CREATE TABLE \"accounts\" (\"id\" INTEGER PRIMARY KEY, \"is_admin\" INTEGER NOT NULL) STRICT"]],"profile":[]}','[]');
COMMIT;
