CREATE TABLE rule_orders (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	quantity INTEGER NOT NULL, 
	status TEXT NOT NULL DEFAULT 'pending', 
	PRIMARY KEY (id), 
	CONSTRAINT ck_quantity_positive CHECK (quantity > 0)
);
