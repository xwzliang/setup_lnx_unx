#!/usr/bin/env ruby
# Applied last to each generated OpenClash config; no network requests here.
require 'yaml'
path, settings = ARGV
c = YAML.load_file(path)
begin
  options = YAML.load_file(settings)
  group = options.fetch('proxy_group')
  groups = c.fetch('proxy-groups', []).map { |g| [g.fetch('name'), g] }.to_h
  nodes = c.fetch('proxies', []).map { |g| [g.fetch('name'), g] }.to_h
  # Unknown destinations / default DNS must never have a DIRECT fallback.
  visit = lambda do |name, seen|
    raise "Proxy group contains DIRECT/PASS or a cycle" if %w[DIRECT PASS].include?(name) || seen.include?(name)
    if groups[name]
      g = groups[name]
      raise "Default proxy group must use explicit nodes (not providers)" if g['use'] || g['include-all'] || g['include-all-proxies'] || g['include-all-providers']
      members = g.fetch('proxies', [])
      raise "Empty default proxy group" if members.empty?
      members.each { |n| visit.call(n, seen + [name]) }
    elsif nodes[name]
      raise "Direct proxy node is not allowed as default" if %w[direct reject].include?(nodes[name]['type'])
    else
      raise "Missing proxy node/group: #{name}"
    end
  end
  visit.call(group, [])
  # Keep explicit subscription/custom routing, including foreign DIRECT rules.
  # Do not classify previously unknown destinations as direct from their IP country.
  rules = c.fetch('rules').reject { |r| r.start_with?('GEOIP,CN,', 'MATCH,', 'FINAL,', 'GEOSITE,cn,') }
  # IP rules must not cause DNS resolution before the domain-based decision.
  rules.map! do |r|
    if r.match(/\A(?:IP-CIDR6?|IP-ASN|GEOIP),/) && !r.split(',').include?('no-resolve')
      r + ',no-resolve'
    else
      r
    end
  end
  c['rules'] = rules + ['GEOSITE,cn,DIRECT', "MATCH,#{group}"]
  d = c['dns'] ||= {}
  d['enable'] = true
  d['enhanced-mode'] = 'fake-ip'
  d['ipv6'] = false
  d['respect-rules'] = false # Explicit DNS dialers below, independent of endpoint-IP rules.
  d['prefer-h3'] = false
  # IP-literal DoH endpoints avoid resolver-hostname bootstrap lookups.
  domestic = ['https://223.5.5.5/dns-query#DIRECT']
  d['nameserver'] = ["https://1.1.1.1/dns-query##{group}"]
  d['direct-nameserver'] = domestic
  d['direct-nameserver-follow-policy'] = false
  d['proxy-server-nameserver'] = domestic
  d['default-nameserver'] = ['https://223.5.5.5/dns-query']
  %w[nameserver-policy proxy-server-nameserver-policy fallback fallback-filter].each { |k| d.delete(k) }
  # Preserve fake-IP exclusions for application compatibility. Their real lookups
  # use the proxied default; DIRECT connections subsequently resolve domestically.
  c['ipv6'] = false
  c['mode'] = 'rule'
  File.write(path, c.to_yaml)
rescue => e
  # Legacy OpenClash ignores hook exit codes. Make the candidate fail closed.
  c['rules'] = ['MATCH,REJECT']
  c['dns'] = {'enable'=>true, 'listen'=>'0.0.0.0:7874', 'enhanced-mode'=>'fake-ip',
              'nameserver'=>['127.0.0.1:9'], 'ipv6'=>false}
  c['ipv6'] = false
  File.write(path, c.to_yaml)
  warn "Split DNS failed closed: #{e.message}"
  exit 1
end
