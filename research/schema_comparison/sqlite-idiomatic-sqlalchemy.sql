CREATE TABLE users (
	id INTEGER NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	nickname VARCHAR(255), 
	status VARCHAR(255) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email)
);

CREATE TABLE teams (
	id INTEGER NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE profiles (
	user_id INTEGER NOT NULL, 
	bio VARCHAR(255), 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE memberships (
	team_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	alias VARCHAR(255) NOT NULL, 
	PRIMARY KEY (team_id, user_id), 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE INDEX ix_memberships_user ON memberships (user_id);

CREATE UNIQUE INDEX ux_memberships_team_alias ON memberships (team_id, alias);
