CREATE TABLE orders (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	price_cents INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	status TEXT DEFAULT 'pending' NOT NULL, 
	created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) NOT NULL, 
	CONSTRAINT ck_price_cents CHECK (price_cents BETWEEN 0 AND 9999999999), 
	CONSTRAINT ck_quantity CHECK (quantity BETWEEN 1 AND 2147483647)
)
 STRICT;
