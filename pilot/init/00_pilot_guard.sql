-- Only initialized within the isolated pilot-db's own volume.
USE gambarte_reconciliation_pilot;
CREATE TABLE pilot_instance_guard (
    marker VARCHAR(80) NOT NULL PRIMARY KEY
) ENGINE=InnoDB;
INSERT INTO pilot_instance_guard(marker)
VALUES ('GAMBARTE_ISOLATED_PILOT_V1');
