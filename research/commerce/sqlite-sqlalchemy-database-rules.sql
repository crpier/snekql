CREATE TABLE rule_orders (
	id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	status TEXT DEFAULT 'pending' NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_quantity_positive CHECK (quantity > 0)
);
