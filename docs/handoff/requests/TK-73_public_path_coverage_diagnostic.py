from pathlib import Path
from scripts.audit.corpus import build_pdf
from packages.document_engine.registry import parse_document
from packages.claim_engine.evidence_consistency import exhibit_rows,check_exhibits,_duplicate_mention_view
from packages.document_engine.reading_text import build_reading_text
scratch=Path('/tmp/impl-10h-c')
for title in ['점검대장','배치기록','장비목록']:
 variants={
  'paragraph': [('p',f'갑 제1호증 {title}, 부록7쪽 확인 부분.'),('p',f'갑 제1호증 {title}: 순서를 설명한다.')],
  'inferred_cells': [('table', [['갑 제1호증',f'{title}, 부록7쪽 확인 부분.'],['갑 제1호증',f'{title}: 순서를 설명한다.']])],
  'explicit_cells': [('table', [['호증','서증명','입증취지'],['갑 제1호증',title,'부록7쪽 확인 부분.'],['갑 제1호증',title,'순서를 설명한다.']])],
  'inline_anchor': [('p',f'갑 제1호증 {title}, 부록7쪽 확인 부분.'),('p',f'이 자료의 내용은 갑 제1호증 {title}: 순서를 설명한다.')],
  'genuine_inferred': [('table',[['갑 제1호증',f'{title}: 동쪽'],['갑 제1호증',f'{title}: 서쪽']])],
 }
 for kind,body in variants.items():
  p=scratch/f'public_path_{title}_{kind}.pdf'
  build_pdf({'name':p.name,'header':'공개 경로 합성','footer':'합성 출처','body':[('h','입증방법')]+body+[('h','첨부서류')]},p)
  doc=parse_document(str(p),document_id='public_paths',filename=p.name,mime_type='application/pdf',sha256='0'*64)
  rows=exhibit_rows(doc)
  dup=[f for f in check_exhibits(doc) if f.confidence_features.get('rule_id')=='EVI.EVIDENCE_NUMBER_DUPLICATE']
  print(title,kind,'tables',len(doc.structure.get('tables',[])),'rows',len(rows),'from_lines',[r['from_lines'] for r in rows],'view_kinds',[_duplicate_mention_view(r)['kind'] for r in rows],'duplicate',len(dup))
