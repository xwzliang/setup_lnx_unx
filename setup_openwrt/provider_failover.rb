# Native Mihomo fallback groups. No monitor, traffic probes or controller writes here.
require 'yaml'
module ProviderFailover
  PREFIX = 'setup-failover/'
  URL = 'https://www.gstatic.com/generate_204'
  def self.apply(config, providers, active_path, directory = '/etc/openclash/config')
    raise 'At least two providers required' unless providers.is_a?(Hash) && providers.size >= 2
    providers.each do |id, file|
      raise 'Unsafe provider identifier/config filename' unless id.match?(/\A[A-Za-z][A-Za-z0-9_]*\z/) && file.match?(/\A[A-Za-z0-9][A-Za-z0-9_-]*\z/)
    end
    preferred = providers.key(File.basename(active_path.to_s, '.yaml'))
    raise 'Active subscription is not in the failover mapping' unless preferred
    # Restore pre-transform groups on repeated verification; rebuild from saved sources.
    old = config.delete('x-setup-provider-failover')
    if old
      originals = old.fetch('original_groups')
      config['proxy-groups'] = config.fetch('proxy-groups').reject { |g| g['name'].start_with?(PREFIX) }.map { |g| originals[g['name']] || g }
      config['proxies'] = config.fetch('proxies').reject { |p| p['name'].start_with?(PREFIX) }
    end
    raise 'Reserved failover name prefix is already in use' if (config.fetch('proxies') + config.fetch('proxy-groups')).any? { |g| g.fetch('name').start_with?(PREFIX) }
    ordered = [preferred] + (providers.keys - [preferred])
    sources = ordered.map do |id|
      c = YAML.load_file(File.join(directory, providers.fetch(id) + '.yaml'))
      nodes = c.fetch('proxies').map { |n| [n.fetch('name'), n] }.to_h
      groups = c.fetch('proxy-groups').map { |g| [g.fetch('name'), g] }.to_h
      [id, [nodes, groups]]
    end.to_h
    # Flatten only proxy-only, static groups. Preserve DIRECT selectors and rules.
    flatten = lambda do |name, nodes, groups, seen|
      raise 'Non-proxy, missing or cyclic group member' if seen.include?(name) || %w[DIRECT REJECT PASS COMPATIBLE].include?(name)
      if nodes[name]
        raise 'Unsupported direct node/dialer dependency' if %w[direct reject].include?(nodes[name]['type']) || nodes[name]['dialer-proxy']
        [name]
      else
        g = groups.fetch(name)
        raise 'Dynamic proxy providers are unsupported' if g['use'] || g.keys.any? { |k| k.start_with?('include-all') && g[k] }
        members = g.fetch('proxies')
        raise 'Empty proxy group' if members.empty?
        members.flat_map { |n| flatten.call(n, nodes, groups, seen + [name]) }.uniq
      end
    end
    originals = {}
    generated = []
    imported = {}
    config.fetch('proxy-groups').each do |group|
      name = group.fetch('name')
      common = sources.values.all? { |_, groups| groups.key?(name) }
      generic = ['Proxy', 'Auto', '🚀 节点选择'].include?(name)
      next unless common || generic
      members = {}
      begin
        sources.each do |id, (nodes, groups)|
          members[id] = if groups.key?(name)
            flatten.call(name, nodes, groups, [])
          elsif generic
            nodes.keys.flat_map { |n| flatten.call(n, nodes, groups, []) }
          end
          raise 'No provider nodes' if members[id].nil? || members[id].empty?
        end
      rescue KeyError, RuntimeError
        # Do not replace selectors with explicit DIRECT choices.
        raise if ['新加坡', '美国', '日本', '新加坡loadbalance', 'loadbalance'].include?(name)
        next
      end
      originals[name] = Marshal.load(Marshal.dump(group))
      children = []
      members.each do |id, names|
        subgroup = "#{PREFIX}#{id}/#{name}"
        children << subgroup
        proxy_names = names.map do |n|
          renamed = "#{PREFIX}#{id}/node/#{n}"
          imported[renamed] ||= sources.fetch(id)[0].fetch(n).merge('name'=>renamed)
          renamed
        end
        kind = group['type'] == 'load-balance' ? 'load-balance' : 'url-test'
        child = {'name'=>subgroup, 'type'=>kind, 'proxies'=>proxy_names,
                 'url'=>URL, 'interval'=>60, 'lazy'=>false, 'timeout'=>5000,
                 'max-failed-times'=>2, 'expected-status'=>'204', 'hidden'=>true}
        child['strategy'] = group.fetch('strategy', 'consistent-hashing') if kind == 'load-balance'
        generated << child
      end
      group.replace('name'=>name, 'type'=>'fallback', 'proxies'=>children,
                    'url'=>URL, 'interval'=>60, 'lazy'=>false, 'timeout'=>5000,
                    'max-failed-times'=>2, 'expected-status'=>'204')
    end
    raise 'No shared Singapore group to protect DNS/default routing' unless originals.key?('新加坡')
    config['proxy-groups'].concat(generated)
    config['proxies'].concat(imported.values)
    config['x-setup-provider-failover'] = {'preferred'=>preferred, 'original_groups'=>originals}
  end
end
