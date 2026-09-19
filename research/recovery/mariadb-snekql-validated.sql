CREATE TABLE `entries` (`id` BIGINT NOT NULL PRIMARY KEY, `code` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL, `quantity` BIGINT NOT NULL, `note` VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin, `occurred_at` DATETIME(3) NOT NULL) ENGINE=InnoDB;
CREATE UNIQUE INDEX `ux_entries_code` ON `entries` (`code`);
