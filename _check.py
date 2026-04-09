from bot.validators import get_all_domains, get_all_subdomains, get_mock_tables, get_mock_fewshots, ALLOWED_SUBDOMAINS

domains = get_all_domains()
print('Domains:', domains)
assert domains == ['sales', 'finance', 'healthcare', 'telecom'], f'MISMATCH: {domains}'

for d in domains:
    subs = get_all_subdomains(d)
    print(f'  {d} subdomains: {subs}')
    mt = get_mock_tables(d)
    print(f'  {d} mock tables: {[t["name"] for t in mt]}')
    for s in subs:
        fs = get_mock_fewshots(d, s)
        print(f'    {d}/{s} fewshots: {len(fs)}')
        assert len(fs) > 0, f'NO FEWSHOTS for {d}/{s}'

print()
print('ALL CHECKS PASSED')
