CREATE TABLE customer (
	id INTEGER NOT NULL,
	name VARCHAR(255) NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE product (
	id INTEGER NOT NULL,
	name VARCHAR(255) NOT NULL,
	current_cents INTEGER NOT NULL,
	PRIMARY KEY (id)
);

CREATE TABLE purchase (
	id INTEGER NOT NULL,
	customer_id INTEGER NOT NULL,
	placed_seq INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(customer_id) REFERENCES customer (id)
);

CREATE TABLE line (
	id INTEGER NOT NULL,
	order_id INTEGER NOT NULL,
	product_id INTEGER NOT NULL,
	quantity INTEGER NOT NULL,
	unit_cents INTEGER NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(order_id) REFERENCES purchase (id),
	FOREIGN KEY(product_id) REFERENCES product (id)
);
