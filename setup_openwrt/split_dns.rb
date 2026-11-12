#!/usr/bin/env ruby
# Applied last to each generated OpenClash config; no network requests here.
require 'yaml'
path, settings, active_config = ARGV
c = YAML.load_file(path)
begin
  options = YAML.load_file(settings)
  protected_dns = options.fetch('dns_protection', true)
  raise 'dns_protection must be boolean' unless [true, false].include?(protected_dns)
  # Restore the pre-policy values before recomputing an already generated config.
  # Fresh OpenClash generation automatically supplies the current subscription's
  # settings; this snapshot also makes on/off preflight and repeated calls safe.
  original = c.delete('x-setup-split-dns-original')
  if original
    c['dns'] = original.fetch('dns')
    c['rules'] = original.fetch('rules')
  elsif c.dig('dns', 'nameserver') == ["https://1.1.1.1/dns-query##{options.fetch('proxy_group')}"] && c.fetch('rules').include?('GEOSITE,cn,DIRECT')
    # Migration from the older transformer, which did not save its input.
    # Keep OpenClash's DNS listener/fake-IP exclusions and explicit custom rules.
    raise 'Active subscription required to migrate old split DNS' unless active_config && File.file?(active_config)
    native = YAML.load_file(active_config)
    d = c['dns']
    %w[nameserver direct-nameserver direct-nameserver-follow-policy proxy-server-nameserver
       default-nameserver respect-rules prefer-h3 nameserver-policy
       proxy-server-nameserver-policy fallback fallback-filter].each do |key|
      d.delete(key)
      d[key] = native.fetch('dns', {})[key] if native.fetch('dns', {}).key?(key)
    end
    native_rules = native.fetch('rules')
    c['rules'] = c.fetch('rules').reject { |r| r.start_with?('GEOSITE,cn,', 'GEOIP,CN,', 'MATCH,', 'FINAL,') }.map do |r|
      plain = r.sub(/,no-resolve\z/, '')
      native_rules.include?(plain) ? plain : r
    end + native_rules.select { |r| r.start_with?('GEOIP,CN,', 'MATCH,', 'FINAL,') }
  end
  old_iot_rules = c.delete('x-setup-iot-rules') || []
  c['rules'] = c.fetch('rules').reject { |r| old_iot_rules.include?(r) }
  if protected_dns
    c['x-setup-split-dns-original'] = Marshal.load(Marshal.dump({'dns'=>c.fetch('dns', {}), 'rules'=>c.fetch('rules')}))
  end
  raise 'Service policies require provider failover' if !options.fetch('service_policies', []).empty? && !options['provider_failover']
  if options['provider_failover']
    require_relative 'provider_failover'
    ProviderFailover.apply(c, options.fetch('provider_failover'), active_config, '/etc/openclash/config', options.fetch('service_policies', []))
  end
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
  visit.call(group, []) if protected_dns
  # Keep explicit subscription/custom routing, including foreign DIRECT rules.
  # Do not classify previously unknown destinations as direct from their IP country.
  rules = c.fetch('rules')
  rules = rules.reject { |r| r.start_with?('GEOIP,CN,', 'MATCH,', 'FINAL,', 'GEOSITE,cn,') } if protected_dns
  # IP rules must not cause DNS resolution before the domain-based decision.
  rules.map! do |r|
    if protected_dns && r.match(/\A(?:IP-CIDR6?|IP-ASN|GEOIP),/) && !r.split(',').include?('no-resolve')
      r + ',no-resolve'
    else
      r
    end
  end
  clients = options.fetch('iot_clients', [])
  raise 'IoT clients must be a list' unless clients.is_a?(Array)
  iot_rules = clients.uniq.map do |ip|
    parts = ip.to_s.split('.')
    raise 'IoT exception requires an exact IPv4 address' unless parts.size == 4 && parts.all?{|p| p.match?(/\A\d{1,3}\z/) && p.to_i <= 255}
    "AND,((SRC-IP-CIDR,#{ip}/32),(GEOIP,CN,no-resolve)),DIRECT"
  end
  c['x-setup-iot-rules'] = iot_rules
  if protected_dns
    c['rules'] = rules + ['GEOSITE,cn,DIRECT'] + iot_rules + ["MATCH,#{group}"]
  else
    # Retain the subscription's GEOIP and catch-all behavior. IoT exceptions
    # remain scoped to their reserved clients and precede the catch-all.
    rules = rules.dup
    if active_config && File.file?(active_config)
      # The retained legacy hook forcibly adds GEOIP,CN,DIRECT. Restore the
      # subscription's own CN rule(s), without discarding other custom rules.
      native_cn = YAML.load_file(active_config).fetch('rules').select { |r| r.start_with?('GEOIP,CN,') }
      index = rules.index { |r| r.start_with?('GEOIP,CN,') }
      rules.reject! { |r| r.start_with?('GEOIP,CN,') }
      rules.insert(index || rules.index { |r| r.start_with?('MATCH,', 'FINAL,') } || rules.length, *native_cn)
    end
    rules.insert(rules.index { |r| r.start_with?('MATCH,', 'FINAL,') } || rules.length, *iot_rules)
    c['rules'] = rules
  end
  if protected_dns
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
  end
  # Preserve fake-IP exclusions for application compatibility. Their real lookups
  # use the proxied default; DIRECT connections subsequently resolve domestically.
  # Apps using cached IPs or HTTPDNS still need domain-based routing. Recover
  # HTTP Host/TLS SNI/QUIC names for rule matching, without changing the chosen IP.
  sniffer = c['sniffer'] ||= {}
  sniffer['enable'] = true
  sniffer['parse-pure-ip'] = true
  sniffer['force-dns-mapping'] = false
  sniffer['override-destination'] = false
  sniff = sniffer['sniff'] ||= {}
  {'HTTP'=>[80, 8080], 'TLS'=>[443, 8443], 'QUIC'=>[443, 8443]}.each do |protocol, ports|
    entry = sniff[protocol] ||= {}
    entry['ports'] = (Array(entry['ports']) + ports).uniq
    entry['override-destination'] = false
  end
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
