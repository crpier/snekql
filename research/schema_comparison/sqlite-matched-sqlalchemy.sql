CREATE TABLE users (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	email TEXT NOT NULL, 
	nickname TEXT, 
	status TEXT NOT NULL, 
	UNIQUE (email)
)
 STRICT;

CREATE TABLE teams (
	id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, 
	name TEXT NOT NULL, 
	UNIQUE (name)
)
 STRICT;

CREATE TABLE profiles (
	user_id INTEGER NOT NULL, 
	bio TEXT, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
)
 STRICT;

CREATE TABLE memberships (
	team_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	alias TEXT NOT NULL, 
	PRIMARY KEY (team_id, user_id), 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)
 STRICT;

CREATE INDEX ix_memberships_user ON memberships (user_id);

CREATE UNIQUE INDEX ux_memberships_team_alias ON memberships (team_id, alias);
