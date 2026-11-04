<?php
$CONFIG = array (
  'htaccess.RewriteBase' => '/',
  'memcache.local' => '\\OC\\Memcache\\APCu',
  'apps_paths' => 
  array (
    0 => 
    array (
      'path' => '/var/www/html/apps',
      'url' => '/apps',
      'writable' => false,
    ),
    1 => 
    array (
      'path' => '/var/www/html/custom_apps',
      'url' => '/custom_apps',
      'writable' => true,
    ),
  ),
  'upgrade.disable-web' => true,
  'instanceid' => 'ochckr9lcyeh',
  'passwordsalt' => 'ujoMWjHOd+pHQ6IGyC99TlfbhUiSFN',
  'secret' => 'YlZ5NRxG4bSyih09NRUocNDYqo3EI2EsAwOYRxIcoU1PAAif',
  'trusted_domains' => 
  array (
    0 => 'localhost:8080',
    1 => '192.168.5.1',
    2 => '192.168.5.201',
    3 => '192.168.5.202',
    4 => 'xwzliang.dynv6.net',
  ),
  'datadirectory' => '/var/www/html/data',
  'dbtype' => 'mysql',
  'version' => '28.0.3.2',
  'overwrite.cli.url' => 'http://localhost:8080',
  'dbname' => 'nextcloud',
  'dbhost' => 'db',
  'dbport' => '',
  'dbtableprefix' => 'oc_',
  'mysql.utf8mb4' => true,
  'dbuser' => 'nextcloud',
  'dbpassword' => '8czfnb',
  'installed' => true,
);
