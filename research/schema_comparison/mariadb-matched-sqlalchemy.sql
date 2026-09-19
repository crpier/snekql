CREATE TABLE users (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	email VARCHAR(255) COLLATE utf8mb4_bin NOT NULL, 
	nickname VARCHAR(255) COLLATE utf8mb4_bin, 
	status VARCHAR(255) COLLATE utf8mb4_bin NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (email)
);

CREATE TABLE teams (
	id BIGINT NOT NULL AUTO_INCREMENT, 
	name VARCHAR(255) COLLATE utf8mb4_bin NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE profiles (
	user_id BIGINT NOT NULL, 
	bio VARCHAR(255) COLLATE utf8mb4_bin, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE memberships (
	team_id BIGINT NOT NULL, 
	user_id BIGINT NOT NULL, 
	alias VARCHAR(255) COLLATE utf8mb4_bin NOT NULL, 
	PRIMARY KEY (team_id, user_id), 
	FOREIGN KEY(team_id) REFERENCES teams (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ux_memberships_team_alias ON memberships (team_id, alias);

CREATE INDEX ix_memberships_user ON memberships (user_id);
