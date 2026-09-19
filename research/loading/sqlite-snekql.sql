CREATE TABLE "customer" ("id" INTEGER PRIMARY KEY, "name" TEXT NOT NULL) STRICT;

CREATE TABLE "product" ("id" INTEGER PRIMARY KEY, "name" TEXT NOT NULL, "current_cents" INTEGER NOT NULL) STRICT;

CREATE TABLE "purchase" ("id" INTEGER PRIMARY KEY, "customer_id" INTEGER NOT NULL, "placed_seq" INTEGER NOT NULL, FOREIGN KEY ("customer_id") REFERENCES "customer" ("id")) STRICT;

CREATE TABLE "line" ("id" INTEGER PRIMARY KEY, "order_id" INTEGER NOT NULL, "product_id" INTEGER NOT NULL, "quantity" INTEGER NOT NULL, "unit_cents" INTEGER NOT NULL, FOREIGN KEY ("order_id") REFERENCES "purchase" ("id"), FOREIGN KEY ("product_id") REFERENCES "product" ("id")) STRICT;
