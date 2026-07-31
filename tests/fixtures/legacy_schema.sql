CREATE TABLE "artists" ("id" integer primary key autoincrement not null, "surname" varchar, "givenname" varchar, "birthyear" integer, "deathyear" integer, "description" text, "composer" tinyint(1) not null default '0', "conductor" tinyint(1) not null default '0', "created_at" datetime, "updated_at" datetime);

CREATE TABLE "auth_logs" ("id" integer primary key autoincrement not null, "event" varchar, "fired_at" datetime, "ip_address" varchar, "user_agent" text, "email" varchar, "payload" text);

CREATE TABLE "booking_logs" ("id" integer primary key autoincrement not null, "performance_id" integer not null, "user_id" integer not null, "booking_type" varchar check ("booking_type" in ('book', 'unbook')) not null, "position_type" varchar check ("position_type" in ('instruments', 'voices', 'choirjobs')) not null, "position_id" integer not null, "fee" integer not null, "notified_at" datetime, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "booking_requests" ("id" integer primary key autoincrement not null, "performance_id" integer not null, "user_id" integer not null, "notbooked_at" datetime, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "bookings" ("id" integer primary key autoincrement not null, "performance_id" integer not null, "user_id" integer not null, "position_type" varchar check ("position_type" in ('instruments', 'voices', 'choirjobs')) not null, "position_id" integer not null, "order" integer not null default '0', "fee" integer not null, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "choirjobs" ("id" integer primary key autoincrement not null, "name" varchar not null, "order" integer not null default '0', "created_at" datetime, "updated_at" datetime);

CREATE TABLE "client_user_agents" ("id" integer primary key autoincrement not null, "string" varchar not null);

CREATE TABLE "fees" ("id" integer primary key autoincrement not null, "name" varchar not null, "amount" integer not null default '0', "created_at" datetime, "updated_at" datetime);

CREATE TABLE "instruments" ("id" integer primary key autoincrement not null, "name" varchar not null, "order" integer not null default '0', "created_at" datetime, "updated_at" datetime);

CREATE TABLE "locations" ("id" integer primary key autoincrement not null, "name" varchar not null, "address" text, "color" varchar not null default '000000', "order" integer not null default '0', "created_at" datetime, "updated_at" datetime);

CREATE TABLE "migrations" ("id" integer primary key autoincrement not null, "migration" varchar not null, "batch" integer not null);

CREATE TABLE "oauth2_bindings" ("id" integer primary key autoincrement not null, "provider" varchar not null, "remote_id" varchar not null, "remote_name" varchar not null, "local_id" integer not null, "bound_at" datetime not null, "lastuse_at" datetime not null);

CREATE TABLE "ordinariumwork_positions" ("id" integer primary key autoincrement not null, "ordinariumwork_id" integer not null, "position_type" varchar check ("position_type" in ('instruments', 'voices')) not null, "position_id" integer not null, "quantity" integer not null, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "ordinariumworks" ("id" integer primary key autoincrement not null, "name" varchar not null, "description" text, "demanding" tinyint(1) not null default '0', "artist_id" integer not null, "duration" integer, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "password_reset_tokens" ("email" varchar not null, "token" varchar not null, "created_at" datetime);

CREATE TABLE "performance_positions" ("id" integer primary key autoincrement not null, "performance_id" integer not null, "position_type" varchar check ("position_type" in ('instruments', 'voices', 'choirjobs')) not null, "position_id" integer not null, "quantity" integer not null, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "performance_proprium" ("id" integer primary key autoincrement not null, "performance_id" integer not null, "propriumelement_id" integer not null, "propriumwork_id" integer not null, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "performance_rehearsals" ("id" integer primary key autoincrement not null, "performance_id" integer not null, "schedule" datetime not null, "comment" varchar, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "performances" ("id" integer primary key autoincrement not null, "schedule" datetime not null, "location_id" integer not null, "ordinariumwork_id" integer not null, "artist_id" integer, "description" text, "choirjob_defaultfee" integer not null, "instrument_defaultfee" integer not null, "voice_defaultfee" integer not null, "extracost_amount" integer, "extracost_description" text, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "personal_access_tokens" ("id" integer primary key autoincrement not null, "tokenable_type" varchar not null, "tokenable_id" integer not null, "name" varchar not null, "token" varchar not null, "abilities" text, "last_used_at" datetime, "expires_at" datetime, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "propriumelements" ("id" integer primary key autoincrement not null, "name" varchar not null, "order" integer not null default '0', "created_at" datetime, "updated_at" datetime);

CREATE TABLE "propriumworks" ("id" integer primary key autoincrement not null, "name" varchar not null, "description" text, "demanding" tinyint(1) not null default '0', "artist_id" integer not null, "duration" integer, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "queue_failed_jobs" ("id" integer primary key autoincrement not null, "connection" text not null, "queue" text not null, "payload" text not null, "exception" text not null, "failed_at" datetime not null default CURRENT_TIMESTAMP);

CREATE TABLE "queue_jobs" ("id" integer primary key autoincrement not null, "queue" varchar not null, "payload" text not null, "attempts" integer not null, "reserved_at" integer, "available_at" integer not null, "created_at" integer not null);

CREATE TABLE "request_logs" ("id" integer primary key autoincrement not null, "client_ip" varchar not null, "client_ips" varchar, "client_user_agent_id" integer, "user_id" integer, "request_method" varchar not null, "request_path" varchar not null, "request_input" text, "response_status" integer not null, "response_content" text, "memory_usage" integer not null, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "roles" ("id" integer primary key autoincrement not null, "name" varchar not null, "label" varchar not null, "description" text, "order" integer not null default '0', "created_at" datetime, "updated_at" datetime);

CREATE TABLE "scores" ("id" integer primary key autoincrement not null, "kasten" varchar, "boxnr" varchar, "auch" varchar, "inhalt" varchar check ("inhalt" in ('Orchestermaterial', 'Chormaterial', 'Orch-/Chormaterial', 'Klavierauszug', 'Orgelauszug', 'Partitur', 'Singstimme')), "surname" varchar, "givenname" varchar, "geboren" integer, "gestorben" integer, "werk" varchar, "teil" varchar, "sparte" varchar check ("sparte" in ('Advent/Weihnacht', 'Bundeshymne', 'Chor', 'Lied', 'Messe', 'Oratorium', 'Orch/Harfe', 'Orch/Orgel', 'Orch/Sakral', 'Orch/Sol/Chor', 'Orchester', 'Passion', 'Sakral', 'Sakral/Solo', 'Symphonie', 'Volkslied')), "verz" varchar, "jahr" integer, "part1verl" varchar, "part1art" varchar check ("part1art" in ('Original', 'Kopie', 'Original/Kopie')), "part1zust" varchar, "part1anz" integer not null default '0', "part2verl" varchar, "part2art" varchar check ("part2art" in ('Original', 'Kopie', 'Original/Kopie')), "part2zust" varchar, "part2anz" integer not null default '0', "klausz1verl" varchar, "klausz1art" varchar check ("klausz1art" in ('Original', 'Kopie', 'Original/Kopie')), "klausz1zust" varchar, "klausz1anz" integer not null default '0', "klausz2verl" varchar, "klausz2art" varchar check ("klausz2art" in ('Original', 'Kopie', 'Original/Kopie')), "klausz2zust" varchar, "klausz2anz" integer not null default '0', "chorpart1verl" varchar, "chorpart1art" varchar check ("chorpart1art" in ('Original', 'Kopie', 'Original/Kopie')), "chorpart1zust" varchar, "chorpart1anz" integer not null default '0', "chorpart2verl" varchar, "chorpart2art" varchar check ("chorpart2art" in ('Original', 'Kopie', 'Original/Kopie')), "chorpart2zust" varchar, "chorpart2anz" integer not null default '0', "stsoprverl" varchar, "stsoprart" varchar check ("stsoprart" in ('Original', 'Kopie', 'Original/Kopie')), "stsoprzust" varchar, "stsopranz" integer not null default '0', "staltverl" varchar, "staltart" varchar check ("staltart" in ('Original', 'Kopie', 'Original/Kopie')), "staltzust" varchar, "staltanz" integer not null default '0', "sttenverl" varchar, "sttenart" varchar check ("sttenart" in ('Original', 'Kopie', 'Original/Kopie')), "sttenzust" varchar, "sttenanz" integer not null default '0', "stbassverl" varchar, "stbassart" varchar check ("stbassart" in ('Original', 'Kopie', 'Original/Kopie')), "stbasszust" varchar, "stbassanz" integer not null default '0', "orgelverl" varchar, "orgelart" varchar check ("orgelart" in ('Original', 'Kopie', 'Original/Kopie')), "orgelzust" varchar, "orgelanz" integer not null default '0', "orchverl" varchar, "orchart" varchar check ("orchart" in ('Original', 'Kopie', 'Original/Kopie')), "orchzust" varchar, "violine1" integer not null default '0', "violine2" integer not null default '0', "viola" integer not null default '0', "cello" integer not null default '0', "contrabass" integer not null default '0', "floete1" integer not null default '0', "floete2" integer not null default '0', "floete3" integer not null default '0', "oboe1" integer not null default '0', "oboe2" integer not null default '0', "klarinette1" integer not null default '0', "klarinette2" integer not null default '0', "fagott1" integer not null default '0', "fagott2" integer not null default '0', "kontrafagott" integer not null default '0', "trombalt" integer not null default '0', "trombten" integer not null default '0', "trombbass" integer not null default '0', "corno1" integer not null default '0', "corno2" integer not null default '0', "trompete1" integer not null default '0', "trompete2" integer not null default '0', "trompete3" integer not null default '0', "pauke" integer not null default '0', "soinstr1art" varchar, "soinstr1anz" integer not null default '0', "soinstr2art" varchar, "soinstr2anz" integer not null default '0', "soinstr3art" varchar, "soinstr3anz" integer not null default '0', "soinstr4art" varchar, "soinstr4anz" integer not null default '0', "bemerkung" varchar, "zusatznoten" varchar, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "sent_emails" ("id" integer primary key autoincrement not null, "from" varchar, "to" varchar, "cc" varchar, "bcc" varchar, "subject" varchar, "body" text, "headers" text, "attachments" text, "mailer" varchar, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "shorturls" ("id" integer primary key autoincrement not null, "path" varchar not null, "target" varchar not null, "counter" integer not null default '0', "latestcall_at" datetime, "created_at" datetime not null, "updated_at" datetime not null);

CREATE TABLE "user_positions" ("id" integer primary key autoincrement not null, "user_id" integer not null, "position_type" varchar check ("position_type" in ('instruments', 'voices', 'choirjobs')) not null, "position_id" integer not null, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "user_roles" ("id" integer primary key autoincrement not null, "user_id" integer not null, "role_id" integer not null, "created_at" datetime, "updated_at" datetime);

CREATE TABLE "users" ("id" integer primary key autoincrement not null, "surname" varchar not null, "givenname" varchar not null, "email" varchar, "email_verified_at" datetime, "phone" varchar, "auth_password" varchar, "auth_remember_token" varchar, "auth_lastlogin_provider" varchar, "auth_lastlogin" datetime, "auth_lastsignal" datetime, "auth_lastlogout" datetime, "auth_locked" integer not null default '0', "administrator" tinyint(1) not null default '0', "created_at" datetime, "updated_at" datetime, "deleted_at" datetime);

CREATE TABLE "voices" ("id" integer primary key autoincrement not null, "name" varchar not null, "order" integer not null default '0', "created_at" datetime, "updated_at" datetime);

CREATE UNIQUE INDEX "artists_surname_givenname_unique" on "artists" ("surname", "givenname");

CREATE UNIQUE INDEX "booking_requests_performance_id_user_id_unique" on "booking_requests" ("performance_id", "user_id");

CREATE UNIQUE INDEX "bookings_performance_id_user_id_position_type_position_id_unique" on "bookings" ("performance_id", "user_id", "position_type", "position_id");

CREATE UNIQUE INDEX "bookings_performance_id_user_id_unique" on "bookings" ("performance_id", "user_id");

CREATE UNIQUE INDEX "choirjobs_name_unique" on "choirjobs" ("name");

CREATE UNIQUE INDEX "fees_name_unique" on "fees" ("name");

CREATE UNIQUE INDEX "instruments_name_unique" on "instruments" ("name");

CREATE UNIQUE INDEX "locations_name_unique" on "locations" ("name");

CREATE UNIQUE INDEX "oauth2_bindings_provider_remote_id_unique" on "oauth2_bindings" ("provider", "remote_id");

CREATE UNIQUE INDEX "ordinariumwork_positions_ordinariumwork_id_position_type_position_id_unique" on "ordinariumwork_positions" ("ordinariumwork_id", "position_type", "position_id");

CREATE UNIQUE INDEX "ordinariumworks_name_artist_id_unique" on "ordinariumworks" ("name", "artist_id");

CREATE INDEX "password_resets_email_index" on "password_reset_tokens" ("email");

CREATE UNIQUE INDEX "path" on "shorturls" ("path");

CREATE UNIQUE INDEX "performance_positions_performance_id_position_type_position_id_unique" on "performance_positions" ("performance_id", "position_type", "position_id");

CREATE UNIQUE INDEX "performance_propriumelement" on "performance_proprium" ("performance_id", "propriumelement_id");

CREATE UNIQUE INDEX "performance_rehearsals_performance_id_schedule_unique" on "performance_rehearsals" ("performance_id", "schedule");

CREATE UNIQUE INDEX "performances_schedule_artist_id_unique" on "performances" ("schedule", "artist_id");

CREATE UNIQUE INDEX "performances_schedule_location_id_unique" on "performances" ("schedule", "location_id");

CREATE UNIQUE INDEX "personal_access_tokens_token_unique" on "personal_access_tokens" ("token")
;

CREATE INDEX "personal_access_tokens_tokenable_type_tokenable_id_index" on "personal_access_tokens" ("tokenable_type", "tokenable_id")
;

CREATE UNIQUE INDEX "propriumelements_name_unique" on "propriumelements" ("name");

CREATE UNIQUE INDEX "propriumworks_name_artist_id_unique" on "propriumworks" ("name", "artist_id");

CREATE INDEX "queue_jobs_queue_index" on "queue_jobs" ("queue");

CREATE UNIQUE INDEX "roles_label_unique" on "roles" ("label");

CREATE UNIQUE INDEX "roles_name_unique" on "roles" ("name");

CREATE UNIQUE INDEX "scores_givenname_surname_werk_teil_unique" on "scores" ("givenname", "surname", "werk", "teil");

CREATE UNIQUE INDEX "string" on "client_user_agents" ("string");

CREATE UNIQUE INDEX "user_positions_user_id_position_type_position_id_unique" on "user_positions" ("user_id", "position_type", "position_id");

CREATE UNIQUE INDEX "user_roles_user_id_role_id_unique" on "user_roles" ("user_id", "role_id");

CREATE UNIQUE INDEX "users_email_unique" on "users" ("email");

CREATE UNIQUE INDEX "users_surname_givenname_unique" on "users" ("surname", "givenname");

CREATE UNIQUE INDEX "voices_name_unique" on "voices" ("name");
