#!/usr/bin/env ruby
require 'yaml'

def uci(*args)
  out = IO.popen(['uci', '-q', *args], &:read).strip
  raise "UCI command failed: #{args.first}" unless $?.success?
  out
end

def optional(key)
  IO.popen(['uci','-q','get',key], &:read).strip
end

def ipv4(s)
  parts=s.to_s.split('.')
  raise 'Invalid IPv4' unless parts.size==4 && parts.all?{|p| p.match?(/\A\d{1,3}\z/) && p.to_i<=255}
  parts.reduce(0){|n,p| (n<<8)+p.to_i}
end

input, mode = ARGV
raise 'Invalid mode' unless %w[check apply verify].include?(mode)
devices=YAML.load_file(input).fetch('devices')
raise 'Device inventory must be a list' unless devices.is_a?(Array)
raise 'Uncommitted DHCP settings' unless uci('changes','dhcp').empty?
router=ipv4(uci('get','network.lan.ipaddr'))
mask=ipv4(uci('get','network.lan.netmask'))
leases=File.readlines(ENV.fetch('IOT_LEASES', '/tmp/dhcp.leases')).map{|l| a=l.split; [a[1].downcase,a[2]]}
sections=uci('show','dhcp').lines.map{|l| l[/\Adhcp\.([^=]+)=host\s*$/,1]}.compact
existing=sections.map{|s| [s,optional("dhcp.#{s}.mac").downcase.split,optional("dhcp.#{s}.ip")]}
ips=[]; macs=[]; pending=[]
devices.each do |d|
  ip=d.fetch('ip'); mac=d.fetch('mac').downcase
  raise 'Invalid MAC' unless mac.match?(/\A[0-9a-f]{2}(:[0-9a-f]{2}){5}\z/) && (mac[0,2].to_i(16)&1)==0
  address=ipv4(ip)
  raise 'Address outside usable LAN range' unless (address&mask)==(router&mask) && address!=router && address!=(router&mask) && address!=((router&mask)|(~mask&0xffffffff))
  raise 'Duplicate device IP/MAC' if ips.include?(ip) || macs.include?(mac)
  ips<<ip; macs<<mac
  matches=existing.select{|s,ms,i| ms.include?(mac)}
  raise 'Conflicting existing reservation' if matches.size>1 || matches.any?{|s,ms,i|i!=ip} || existing.any?{|s,ms,i|i==ip && !ms.include?(mac)}
  raise 'Live lease conflict' if leases.any?{|m,i|(i==ip && m!=mac)||(m==mac && i!=ip)}
  raise 'No matching live lease or reservation' unless leases.include?([mac,ip]) || matches.size==1
  if mode=='verify'
    raise 'Reservation missing after apply' unless matches.size==1
  elsif matches.empty?
    section='iot_'+mac.delete(':')
    raise 'Managed section name already exists' unless optional("dhcp.#{section}").empty?
    pending<<[section,mac,ip]
  end
end
if mode=='apply'
  pending.each do |section,mac,ip|
    uci('set',"dhcp.#{section}=host")
    uci('set',"dhcp.#{section}.mac=#{mac}")
    uci('set',"dhcp.#{section}.ip=#{ip}")
    uci('set',"dhcp.#{section}.name=iot-#{mac.delete(':')}")
  end
  uci('commit','dhcp')
end
puts "IoT reservations #{mode}: #{devices.size} devices, #{pending.size} new"
