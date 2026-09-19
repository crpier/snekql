CREATE TABLE `users` (`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, `email` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, `nickname` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin, `status` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB;

CREATE UNIQUE INDEX `ux_users_email` ON `users` (`email`);

CREATE TABLE `profiles` (`user_id` BIGINT NOT NULL PRIMARY KEY, `bio` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin, FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE) ENGINE=InnoDB;

CREATE TABLE `teams` (`id` BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, `name` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL) ENGINE=InnoDB;

CREATE UNIQUE INDEX `ux_teams_name` ON `teams` (`name`);

CREATE TABLE `memberships` (`team_id` BIGINT NOT NULL, `user_id` BIGINT NOT NULL, `alias` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, PRIMARY KEY (`team_id`, `user_id`), FOREIGN KEY (`team_id`) REFERENCES `teams` (`id`) ON DELETE CASCADE, FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE RESTRICT) ENGINE=InnoDB;

CREATE UNIQUE INDEX `ux_memberships_team_id_alias` ON `memberships` (`team_id`, `alias`);

CREATE INDEX `ix_memberships_user_id` ON `memberships` (`user_id`);
