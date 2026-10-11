from pathlib import Path
import runpy
from packages.claim_engine.evidence_consistency import exhibit_rows,_duplicate_mention_view
m=runpy.run_path('tests/test_tk73_exhibit_reading_provenance.py')
for prefix,title in [('각 ', '점검기록'),(') ', '배치대장'),('. ', '보관표')]:
 for ext in ['pdf','txt']:
  lines=['입증방법',f'갑 제1호증 {prefix}{title}',f'갑 제1호증 {title}: 순서를 설명한다.','첨부서류']
  doc=m['_parsed'](Path('/tmp/impl-10h-c'),ext,lines); rows=exhibit_rows(doc); views=[_duplicate_mention_view(r) for r in rows]
  print(prefix,title,ext,'original name',rows[0]['name'],'anchor',views[0]['fallback'],'proposed',views[1]['title_key'],'duplicate',len(m['_duplicates'](doc)))
