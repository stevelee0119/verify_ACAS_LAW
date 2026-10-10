"""TK-72 직접 만든 합성 입력의 공개 기준 03fdcdb 출력 계약.

기준 모듈에서 한 번 기록한 모든 필드의 SHA-256을 비교한다. 03fdcdb의 공개
citation_extractor.py를 별도 모듈로 로딩하여 아래 _samples의 텍스트/문서 경로를
각각 실행한 출력이다. 필드 누락 없이 sort_keys=True, separators=(",", ":") JSON의
UTF-8 바이트를 기록했다. 원본 출력 272건 비교도 차이 0이다. 변경한 것은 무작위 인용 ID 및
continued_from의 ID 표현뿐이다. 기존 시험/평가 자산을 수정하거나 복사하지 않는다.
두 자리 연도 헌재의 회복된 분류는 2026-10-10 사용자 승인 예외로 따로 시험한다.
"""
from dataclasses import asdict
import hashlib
import json
import random
import time

import pytest

from packages.common.enums import CitationType
from packages.common.schemas import Block, NormalizedDocument, Page
from packages.legal_engine.citation_extractor import (
    ACADEMIC_RE, SpanTracker, _author_start, _interpretation_matches,
    extract_citations, extract_from_text,
)

def _samples():
    cases={}
    for i,ws in enumerate((' ', '  ', '\t', '\n', '\r', '\u3000')):
        cases[f'statute-space-{i}']=f'「민법」 제750조{ws}제1항. 「형법」 제250조{ws}제2항.'
        cases[f'reference-space-{i}']=f'「민법」 제750조{ws}같은 조 제2항 및 제3항.'
        cases[f'claim-space-{i}']=f'원고는{ws}「민법」 제750조{ws}손해를{ws}청구한다.'
    for i,prefix in enumerate(('', '앞말', '김가나다라마바사', '(', '1. ', '가. ', '본문\n', '말. ')):
        for j,delim in enumerate(('·', ',', 'ㆍ', ' · ', ',\n')):
            cases[f'author-boundary-{i}-{j}']=prefix+delim.join(['김가나','이다라'])+', 「합성 논문 제목」, 법학논총, 2024'
    for count in (11,12,250):
        names=[f'저자{chr(0xAC00+i)}' for i in range(count)]
        for i,delim in enumerate(('·', ',', ',\n', ' · ')):
            cases[f'authors-{count}-{i}']=delim.join(names)+', 「합성 학술 자료 제목」, 합성논총 제2권 제3호, 2024'
    for i,(op,close) in enumerate((('「','」'),('『','』'),('“','”'),('"','"'))):
        for j,publisher in enumerate(('법문사', '법학 논총 제 2권 제 3호', '  ', ' 가')):
            cases[f'publication-{i}-{j}']='김○○, '+op+'합성 학술 자료 제목'+close+', '+publisher+',2024'
    for i,prefix in enumerate(('"합성 설명을 직접 인용한다"라고 주장한다(', '“합성 설명을 직접 인용한다”라고 주장한다(', '앞의 "따옴표를 닫지 않았다 ')):
        cases[f'overlapping-title-{i}']=prefix+'김○○, 「합성 학술 자료 제목」, 법문사, 2024)'
    for i,text in enumerate(('「일반 합성 계약 제목」에 동의한다.', '김가나·'*10+'끝난 저자 목록.', '자료명, 「합성 학술 자료 제목」, 법문사, 1800', '김가나, 「짧다」, 법문사, 2024', '김가나, 「합성 학술 자료 제목」, 2024', '김가나, 「합성 학술 자료 제목」, 법문사, 2024')):
        cases[f'academic-control-{i}']=text
    for i,text in enumerate(('헌재 2024. 1. 2. 2023헌바100 결정', '헌법 재판소 2024. 1. 2. 2023헌마101 결정', '대법원 2024. 1. 2. 선고 2023다100', '서울행정법원 2024. 2. 3. 2023구합101', '2023도102 판결', '법제처\n  법령해석24-0001', '국방부 유권해석 24-0002', '법무부  유권해석례 24-0003', '법제처 2024. 1. 2. 회신 24-0004 해석례', '중앙행정심판위원회 2024-100 재결', '「민법」 제750조 및 제751조 및 같은 조 제2항.', '「민법」 제750조 제1항, 같은 조 제2항 제3호, 제4항.', '국방부 훈령 제2345호 제2조 및 제3조에 따른다.', '「합성 시행 지침」(교육부 지침 제2468호) 제2조에 따라 대외적 구속력이 있다.', '「합성 법률」 제3조의 위임에 따라 교육부 훈령 제2469호는 적용된다.', '같은 법 제2조는 단독으로 해결하지 않는다.', '「민법」 제750조 및 제751조\n「형법」 제250조, 같은 조 제3항.')):
        cases[f'other-{i}']=text
    for i,brackets in enumerate(('({})', '[{}]', '( ( {} ) )', '({})()', '[]({})', '({}, {} )')):
        line=brackets.format('대법원 2024. 1. 2. 선고 2023다100 판결','대법원 2024. 1. 2. 선고 2023다200 판결')
        cases[f'long-case-{i}']='원고는 '+line*30+' 판결을 원용한다.'
    for i,prefix in enumerate(('1. ','가. ','원고는 ','123) ','(근거, ')):
        cases[f'long-statute-{i}']=prefix+'손해배상(「민법」 제750조), '*40+'주장을 한다.'
    cases['long-lead']='가'*1500+' 「민법」 제750조, '*30
    cases['quote-repeat']='"합성 직접 인용문을 제시한다"(대법원 2024. 1. 2. 선고 2023다100 판결), '*30
    cases['academic-repeat']=('김가나, 「합성 학술 자료 제목」, 법문사, 2024.\n')*30
    cases['mixed-repeat']=('「민법」 제750조, 같은 조 제2항.\n김가나·이다라, 「합성 학술 자료 제목」, 법문사, 2024.\n대법원 2024. 1. 2. 선고 2023다100 판결.\n')*10
    for i,text in enumerate(('법제처 24-0005', '법제처 2024. 1. 2. 24-0006', '법제처  24 - 0007')):
        cases[f'interpretation-number-only-{i}']=text
    cases['alias-defined']='「합성 거래에 관한 법률」(이하 \'합성법\'이라 한다) 제3조. 합성법 제4조.'
    cases['alias-prefix-unique']='「합성산업 관리법」 제3조. 합성산업법 제4조.'
    cases['alias-prefix-ambiguous']='「합성산업 관리법」 제3조. 「합성산업 촉진법」 제4조. 합성산업법 제5조.'
    cases['alias-no-space']='합성산업관리법 제3조. 합성산업법 제4조.'
    cases['alias-short']='「합성 관리법」 제3조. 합성법 제4조.'
    cases['alias-equal-clean']='「합성산업 법」 제3조. 합성산업법 제4조.'
    return cases

_TEXT_OUTPUTS = json.loads(r'''
{
 "statute-space-0": [2, "249c0380a872f730ff3163609027b17808c6241378423ccfe56e7d2bee5971a7"],
 "reference-space-0": [3, "e783052d59934b4393ea75080f12bd11515bf056848414a8bd33ef1800e8dcdf"],
 "claim-space-0": [1, "943a42446bace08829f25828b873931bae6510933313eebcf68b67eb314b092e"],
 "statute-space-1": [2, "9e6509f421dc421eeaafbfc9d59c007d5d17d906537fde73a972d5bbc6e83c9f"],
 "reference-space-1": [3, "ab47fecb5e36ea11c3a035c207d6d8d3670be4a8e60c4dd028d4633a579822e6"],
 "claim-space-1": [1, "a030adcef5694bcafca03819c74b26f16f70d360ae9e3d8c990fd8691b5cf6d4"],
 "statute-space-2": [2, "8554a5d64988d9d1dfde64081356716081ff3b66326e72683e3720b1dc48883f"],
 "reference-space-2": [3, "f3d5a0f200d5d0464d129d4008260512cf7509f54464cbf4e0af7a25923399e4"],
 "claim-space-2": [1, "682c12825808f64f9cbe61a0982e7cf9bf9f6de1e00496ee6de0dc48e9949f64"],
 "statute-space-3": [2, "5a56a588708e7982a5fa6319535cd58e451970b82bb55a2b3b85cb90d3c6bb6c"],
 "reference-space-3": [3, "50e6990a5e987e0259c35396e84165e9a81fa420db89d3c132f904a9e0be23dc"],
 "claim-space-3": [1, "dbe7d7ba23fa8b18b94193b2c0fec7ab9ecb5abfbc6183f64cff2fa0b0b2a5ad"],
 "statute-space-4": [2, "d51a6727321d234a45f9c55a94dea6a973030e6e17fcd3f5b570ae42ff6ee5b4"],
 "reference-space-4": [3, "0df99fb91c176bcaeab3efccf5d196e0d62c3032f4f78359d612c49acf393d30"],
 "claim-space-4": [1, "1dcc39c3ad97c03e0b0e8f1b3e0d87e5fd52ca17e0369be6cb363e715f577256"],
 "statute-space-5": [2, "03430b38e618c1a8bf162d93664a20189028c46b53901a887e752be526f33ed9"],
 "reference-space-5": [3, "39847fdd1e129e0a264dfa8ee71af2c7d6a3c66d3f8f228352cbf43d7e4704d6"],
 "claim-space-5": [1, "662fff52698e0c2ffb29c98744a06e74d83184a5a994f38651bf253b07c14c9d"],
 "author-boundary-0-0": [1, "dfad0e244b0797d8db8c3c9fcfb7bf048012f258d71375bc19473e2867e3192c"],
 "author-boundary-0-1": [1, "88d8eac7ed8e516cf1c9919e1708b150012e22cb4905feb6639d09138ee016eb"],
 "author-boundary-0-2": [1, "83413f4efac21b56a5c6a08efbee2a72a22b66eb2e487046df15ba941ce98144"],
 "author-boundary-0-3": [1, "b90eb8b0f703b4f4d81754e613ec526cd62d7d9d34c44b5d025f728d79a47648"],
 "author-boundary-0-4": [1, "221143149606dec14a2319d730205444b857762d1bb307631a06f23590f805a6"],
 "author-boundary-1-0": [1, "8306ef0e59d2ae75b9160651a33541e5e716d5e02ffd053e453cc45309a6a98e"],
 "author-boundary-1-1": [1, "461922c0db3b84c31031082be4c37311fb70f27a158d96e60693dcfb5132e8f6"],
 "author-boundary-1-2": [1, "2ffb62a8546bcb3c0eeb4d6dc08b29d185b6679ddbfdaf27f84148e51c983fe4"],
 "author-boundary-1-3": [1, "7f63ff31cfd764431e741ccb893787e0ea9b3138962423f488797af442607714"],
 "author-boundary-1-4": [1, "4326f7578732c2742cbde4b926c9f63e4640c3d688a4c2882359c3957d570122"],
 "author-boundary-2-0": [1, "5f8c42ab87174078724ec4c3c21d658c14e9ef56f620df8891782589d17d6604"],
 "author-boundary-2-1": [1, "44fee17247f6c26535ff1d0ce88a09bfaf22ea636b0a0535b117ca4b39720281"],
 "author-boundary-2-2": [1, "4c32ea53f5be38fc16687fb0ccfd196dc2950144dd3f8bc59ffd75cfc1e3fda6"],
 "author-boundary-2-3": [1, "eecd17b13467e0fc000cfa5bd0ff6c7a3dac0d4954a6f5ebcf356060d7ca3e72"],
 "author-boundary-2-4": [1, "68ad59a02fa502e2b78eed1afe2c56923684fe961e3bef582d3ade4f7d89979f"],
 "author-boundary-3-0": [1, "31625fa8b08a10215ada759dbd4eebe72ba4824d56d886817565d5c32f6f97a1"],
 "author-boundary-3-1": [1, "318aae2ffb1e96a1db7effadb40b0b4ba35a2c5791934668aa2cd9acdd1959f4"],
 "author-boundary-3-2": [1, "0d310a6e1a3039b61f0b9b6c4f2aa0017a4c2c84cdaa175937e768a5ba9e4573"],
 "author-boundary-3-3": [1, "161d85451918b7b47d88f501b1925cb60277ab6024ec3c85480ab1b1fa12447b"],
 "author-boundary-3-4": [1, "1cf2b3e62827b078098bc6a0faf31bc21323052987a7e3d49e549963b6fcf0bc"],
 "author-boundary-4-0": [1, "d88ae743b9e30393511dc5ca53953fd334fbd1233c8c10347c0681eab6b97b61"],
 "author-boundary-4-1": [1, "395014ed6c56553f0260f3f17ee44d256e1f0de7e859a54ea83d74a9b15282c0"],
 "author-boundary-4-2": [1, "4ad2098227049a44554eba0cf7d466b9966f1f4d8b9adc9c32b2668d65da1171"],
 "author-boundary-4-3": [1, "4b94ae2e275a81636850355287fec203bc780631c5ebcde1f244bdf9ad1a197e"],
 "author-boundary-4-4": [1, "d83919b721b0a770e98617ea0a4e6d8813d85dd97204d8c86430ba4b6e03d2e8"],
 "author-boundary-5-0": [1, "c24743d9d36dc31c59394182c4b80f36b8f9395bfbf048ea867c1570968f967a"],
 "author-boundary-5-1": [1, "419709936c8970af1d3fd208283eb94f0c3d56690a08341ab513b45bfd633742"],
 "author-boundary-5-2": [1, "88d57e0a9e719dc8cb74c20fb24c3d3fd80e931e32dd4df97f1e2c5c47aa8c5c"],
 "author-boundary-5-3": [1, "7952c9f4c1c08a61d6e9984af2c5e048dcb7ec5e8bf5f48d124a87587ceeb737"],
 "author-boundary-5-4": [1, "dbe6c9f142baaaf2bd58c339ddd1b361668dcf92867a8d116caf1177f281b9fd"],
 "author-boundary-6-0": [1, "6b009a9fc40c850b44c238925b53b6e7abe3e2a1d00fa6202ed7294177fecd85"],
 "author-boundary-6-1": [1, "4aa707d83b67d73c338b59e51b001dd19f251428481ee5ec22e6e12ceb44610e"],
 "author-boundary-6-2": [1, "f0651f625783b7f60962bfc2d7f897f8ebd9707aa98b3859db71d040f6d4f76c"],
 "author-boundary-6-3": [1, "1c18ceb5fc90ece0854dc46260498a8d292735aa03bf98d9c7fbd88b396f8fc6"],
 "author-boundary-6-4": [1, "cbeaafbdd020cf6ea233d02d41d3de594bf2bfcaa7d79eb6f6c36b51368239c5"],
 "author-boundary-7-0": [1, "af2a5461b4ff860ed75c39caddcfcbcb9aa86bc2339bb82a136bc2be04cc6b5d"],
 "author-boundary-7-1": [1, "73406e80aae175a252124c50aae70ecb7c6f02664680874c358af3753f57e587"],
 "author-boundary-7-2": [1, "dd9bb565894eddf5c7e4e989c83f022d4877d5d955a319c90f426062131624ed"],
 "author-boundary-7-3": [1, "ff51963a46dd4a7c4b00545931e87a3136d77bc6ea974a878c99897d331712e6"],
 "author-boundary-7-4": [1, "c5f1edafd545c52cde4d34f79e698c2e7ec1fabce48ae34fb02f16457b37ea94"],
 "authors-11-0": [1, "43ed36eb40218289cfc178aadcc54c94629eba232124bd1cd6fd3a9ed1da22bd"],
 "authors-11-1": [1, "5476b863db9f9aba33b3733cd08ac38f3542eed48d49446eb7fb065c5df3d3b0"],
 "authors-11-2": [1, "961c883543ae5f2b1c819e82130ef534fa4e89ed6b86842bb4ed1dc3868b0432"],
 "authors-11-3": [1, "206f3fc1ee74056b9e181a82d3f79b609e8048049aa4c576f381aab3ccdfe7bd"],
 "authors-12-0": [1, "eab8e48e4dc436c26b9db573ae800fafc88b738690ffd1de9fb9194d6b41619c"],
 "authors-12-1": [1, "f2d520c347ffd8d2bc4aed37b089c2244f1c125b2c59b2035a747b50f7a00cad"],
 "authors-12-2": [1, "11aa83fa9064c2340dbeb9926b41270b21cb6b4e759e89beb5c034891797d8c5"],
 "authors-12-3": [1, "d6099da00836db716c875b3daec463e3288b5530d4fd45945cf2200c9426af0c"],
 "authors-250-0": [1, "29b5e9f3dbf9731f63fdaff9c3e75b299943bda099323a02d15341461e47c673"],
 "authors-250-1": [1, "49cbbcbd6e57bde0713636d818b675ddd76b4a50ef1b8fccfca15f2d6e98b3c0"],
 "authors-250-2": [1, "80e8b698affa27511e655f75bffd40a287ad5f1c9b233b5cdd2fe8e674561c98"],
 "authors-250-3": [1, "ce6920abee403a304e171e9ec362211ceadb0102ff9a1f080bfecb8d736f7e23"],
 "publication-0-0": [1, "506e70667729848621b972a72fa7c082ceb7e3f377c57dd49d6cfd0efc5bfd6e"],
 "publication-0-1": [1, "ef27795c04861215cfec6743f361f1246a12ae84b73299db0b683465c34a7b80"],
 "publication-0-2": [1, "665703241e9007c36ec82cb52c84235e10c2b4ef0d7c51d94d61ab49f8911180"],
 "publication-0-3": [1, "cf111f909b0e5ae326dd25a9d4ed9756efeeb149037f8c25556fdb76d28dd320"],
 "publication-1-0": [1, "0021c5dd4a191ad8d067a0f35b8e7f27c6e6fce6f07b00756d83e6dd20e3c169"],
 "publication-1-1": [1, "79a34cde0631b28e15d4db51ef47828e5ca564a567e2fc4435e8ee8c9b327037"],
 "publication-1-2": [1, "6f0e0ff83b5669339206913f1992403a16582edde94538f1ce33eec69ba08fbf"],
 "publication-1-3": [1, "cea2299929e4a0111ae1f1790640bc008244f594cf0285d81cdd76e06a74ba78"],
 "publication-2-0": [1, "d5e79ede9139b0487a6e3bceadb18d3b6405df4d074b11a81a0c5219c9e30a0f"],
 "publication-2-1": [1, "da98dd017d65d47f3eda40f33b2ba9de3a29b81535678b86e3ac23cfb06ef7d2"],
 "publication-2-2": [1, "56f5cf32e4b060dad97c2faf708fcfecc55ed9ce43bc132e7d38165b10dc2fd7"],
 "publication-2-3": [1, "4fcec46577d47e51c3f863444f6d136e691e24cbf86c5668d0608db0a5ec8291"],
 "publication-3-0": [1, "220f4515a2ccd67c3de1ad25698e5b37655d99ab19565dad2277623c2e248a0f"],
 "publication-3-1": [1, "344009922a13995319b78693cefbaee24917dc242a9b304358def8ab8ebdf5e3"],
 "publication-3-2": [1, "e5bf041371fb6c8c466e669418012cc3b9c74a74004d2fe76bbef9a8a2dccac6"],
 "publication-3-3": [1, "03eb8bbc88d96dfb2b5780822294fed5496ddfa512737e115a1c0b1c1ec6bf46"],
 "overlapping-title-0": [1, "af96eb672f3a8541082425cf0f470b6d088309d9cbddc4cf60a31980621bd125"],
 "overlapping-title-1": [1, "5a5cacf999038b85277f5cf3c46752911797019ab0a6822ebfd9582df723e024"],
 "overlapping-title-2": [1, "d5e33b160df060a84c2958a4a1e6b835cfae63e325d5a05a205153fee8c0d694"],
 "academic-control-0": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "academic-control-1": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "academic-control-2": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "academic-control-3": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "academic-control-4": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "academic-control-5": [1, "d7948ecebbc81a2e9fce4e8bce00f3122d5c979ed56fe6a104401ca05e6bff32"],
 "other-0": [1, "f75aead46b0535f91fc2f503bc891703082df48fa85c4b117656f591f728b67f"],
 "other-1": [1, "216a6b1568dbcb63c9223d6f290263a3e9c0abffcb9f0e1e5a929fc1c0cc6325"],
 "other-2": [1, "9c8cb8e772757517aff66ade1c8d316144d9927f9c6a4bdffb9540cac7779283"],
 "other-3": [1, "573e85d16637b33a8a79dadcfa484047d1566fca466704dbf5513b5075deaf6b"],
 "other-4": [1, "3719364bd5df4026d5256bef247064d213e513c6f4f8965b457b79d555c1a7aa"],
 "other-5": [1, "e4c706c17a5833931edf61619faab1043d7c63b3a3840b5f8032f397b19e07b2"],
 "other-6": [1, "0c0abedc67ecadd407c114c0deeddb37050316f40eefe5d2199b2fc13b4e5e90"],
 "other-7": [1, "ed01c75efb78cb81f09c3760fa87ddf12b3c6b1c71873602616c20ae1e3b816f"],
 "other-8": [1, "4dae77e11799a74ffc59f137af6f1024c5f6e1dbaf69ef967c6f3d14dd0ccd94"],
 "other-9": [1, "c1ee394a000c4c5e41e1631aa040328c8d77780b9fca28ec3ab7ba2bbba1b5b8"],
 "other-10": [3, "999811d619545a98ff987a7647d2112bac54718666b1a46b95080d09a8ef302f"],
 "other-11": [3, "5e3ccfc90e228cd21ef159c09afa24219d9909ac52b834acb616e2f2c7a2ff29"],
 "other-12": [1, "e84d673e3b43eb017e8d75b3be56bb6ff0b0901c501278cf8d7282437ad3af8a"],
 "other-13": [1, "6965acdf808ff2d75d387c8a71b55df0eacc57e5b53ce87723b56c8a001bb0e6"],
 "other-14": [2, "526e714cae01b19c2f0dcc0a7f2ab77f07816f481f3caaa7d51c9336e7561fe0"],
 "other-15": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "other-16": [4, "0fb91ebd8f5e54441913a489797513e9840ab52eeb93c2d47f9c286c25bf6487"],
 "long-case-0": [30, "61521cd0c4659a7f43117ee7370b943651a7535136e94bff2275630edeb629b5"],
 "long-case-1": [30, "4b5617e57d87199108db56585ccc4090715f1fe98c2db665193274469291105c"],
 "long-case-2": [30, "7c2ba9662903c3d7b33d28ccc1735ac17f115b4f35c96c1dd7ff26310221b938"],
 "long-case-3": [30, "6b1cebe7d310357cc943718b498457fac620df64281b93ac8e357a0c5716000f"],
 "long-case-4": [30, "2aa7923a7340fb62813ab5b956b267f9589bb40d23be9292be4079846d0704b7"],
 "long-case-5": [60, "02ebb33e1045fd691f11a3a5d1bb51f0d895461ce5eb639719d82eee3a8464a7"],
 "long-statute-0": [40, "fde5329f091d767174a6a650f0ccaaaf2fa9ca6eb6b70e1f0d7c6b75b2bc9966"],
 "long-statute-1": [40, "80bbfad7674f20cfc15f720fbd1a5f155e02cb898eef50a7006166fb283123b7"],
 "long-statute-2": [40, "f67f3c86194e3ad68d497e255fb87024a21aff2da3534e0e38d35fe406c2e234"],
 "long-statute-3": [40, "42f372774b4a0171fab0ad2a8605f55946f9c8d19a391b525d3e23ef6bff597e"],
 "long-statute-4": [40, "2d5cada95607ab06eccc0c63b1ac652812447b92b903c4b50ba9084a10381519"],
 "long-lead": [30, "223578b7ae291bf59743b766304b25da20c26ff003c802bd2f5f1f340fb016f2"],
 "quote-repeat": [30, "05f906f98e19ce485bd1b5092d072b6925f6d0d90b500c854abddda4c3b427c6"],
 "academic-repeat": [30, "70c4944df1175bcb13790a905483d0b0e978c6fc73534caf7e4201a613ab7b6e"],
 "mixed-repeat": [40, "93c73b3179e2de8a978f2de04cf6a62e3b1a57d048567ed85cc0a1027377e2b3"],
 "interpretation-number-only-0": [1, "a96bdfb9511bab91017aa69f484ed98c793feadc1ab801d623afd72504195b9f"],
 "interpretation-number-only-1": [1, "70b108596a44de6acc2ec0599932eaa25edd59c1ca1639946542d40c595a80d8"],
 "interpretation-number-only-2": [1, "bc9f03ccc60dd65e6292330c3ee6464db6606a000a442670c906c5eb3fb81644"],
 "alias-defined": [1, "1d2391340980c95cf67bccd7d8c486051630899a79524b2b3f632fd37728ec34"],
 "alias-prefix-unique": [2, "95af113af7385b14ccd1bbc97060cb305f7551f43f526da4350301620976ae1d"],
 "alias-prefix-ambiguous": [3, "2c6082e683a178930de628885c6fb2b148c6c9579f72a525b044bc709ea37a11"],
 "alias-no-space": [2, "f21232f4c3ad115be919950f5f041a0ed9f9b2f9f4fbe260fd3c39d31d7f0aa5"],
 "alias-short": [2, "255086256cccece296376471f90d9ca3a877b5af3b6c8e3968aab6e678fd6c56"],
 "alias-equal-clean": [2, "d7b57e86840bb62eaf2fbd3f9c5826c14cde15138eb1cf919d0c92cf93ae02c9"]
}
''')

_DOCUMENT_OUTPUTS = json.loads(r'''
{
 "statute-space-0": [2, "bb89c73530edd7de3e2981b2e8937b6dfb3494fbed645ecd738c2586903353a1"],
 "reference-space-0": [3, "a3208ae40aaed2447097da5a32aab0412233f06972d355745f5d084cf9f23c0a"],
 "claim-space-0": [1, "c8eca279327b81b77db0e8f5751c552d90c8eaa9d935cf007bd517db27727356"],
 "statute-space-1": [2, "3296599075e671036e9dab55f2ea294b03517ae561c6c0c5205821d82e5c0901"],
 "reference-space-1": [3, "b86721f613735b1ba531945d58c6aa1bd661bb3822d2d9065418e32681fc6b80"],
 "claim-space-1": [1, "c1a7b3351e0517565bc4eaa49df3bdcde5cbb8de39707182ae82e66bfd2fbaf6"],
 "statute-space-2": [2, "6069bc66e9120761f1b75fb65d3aa7256a55092e85da97aff105884207b31081"],
 "reference-space-2": [3, "51d3a38215a809ccf83281424feffed0c6042bdbaf8818184131c6f924adf8c1"],
 "claim-space-2": [1, "1be67fe773fa45c3fe0e4d96f58e1db2093f7d6d65525fc668bcadbaf379b309"],
 "statute-space-3": [2, "b872588b5f6930c3ba257e56095c2da49e96b5404a32cb53ce3264e10323c87e"],
 "reference-space-3": [3, "5ef83cd469d2066d1632101ddab87ce9c70eb3ef7e7d18998a38a4e6d2f097d8"],
 "claim-space-3": [1, "69ffffe3a934bb239be5a31a63dfb718f26e36dd05bd72f4c1f7797b8add94e8"],
 "statute-space-4": [2, "aca7694a8cd3a19f398ba031c6a98755893c3981828c8dee5cf58d6636e68b97"],
 "reference-space-4": [3, "f064856d35fee82c9e293f823591f16512955f7caeb22b9819dc4e9cd5605bcf"],
 "claim-space-4": [1, "eb8db59ce7219a6848fced14f2df5fdaafde4aef98d9f77ea98cb0dc7ff49bde"],
 "statute-space-5": [2, "bb89c73530edd7de3e2981b2e8937b6dfb3494fbed645ecd738c2586903353a1"],
 "reference-space-5": [3, "a3208ae40aaed2447097da5a32aab0412233f06972d355745f5d084cf9f23c0a"],
 "claim-space-5": [1, "c8eca279327b81b77db0e8f5751c552d90c8eaa9d935cf007bd517db27727356"],
 "author-boundary-0-0": [1, "6236dd92fe00245ad16ce445872c72da77c545e95698245a5f968fb69dac10e7"],
 "author-boundary-0-1": [1, "ba88c9c51dc0f79652a0c29e21518b670b9bc7718326053e534621667f532f60"],
 "author-boundary-0-2": [1, "b34066b429def6d13e9fdd5319df7eb470b997c2aada49b2cc48a6e55c278f3d"],
 "author-boundary-0-3": [1, "46c637986cb2ec755fe5982f96973c177d383471896be2af1836343ac722e890"],
 "author-boundary-0-4": [1, "ef42d54836b9127a7028551e3d0fa07f5487baff7fbc8508a74d508ff0729ca0"],
 "author-boundary-1-0": [1, "043498ec54ea219ec5c9e49c87a0230cd012951b1ae372797c3ffe57b84e69c2"],
 "author-boundary-1-1": [1, "05af01231558ac30e4c9b726c8004010a857c50110457bd196f7c7816f561c35"],
 "author-boundary-1-2": [1, "f2af69f2abc2e511955178453cbe55cbde83c0cd502c9557b58a27c321a9e8eb"],
 "author-boundary-1-3": [1, "e3176a0814151999de097d42445cc1ae06bf83021a346388b9fe4eb613545961"],
 "author-boundary-1-4": [1, "f9346f469f41e24994ee06c2bae2d4cddf74b730ef3d1314b459134d286340a5"],
 "author-boundary-2-0": [1, "02b438d99aec2fe498d8d8339eeb1948e070bc7d2b274c83969612f93c293797"],
 "author-boundary-2-1": [1, "ffda9b42ee69139df1233f3674dea642344872bc60b0ddcded7d9183f3094b6e"],
 "author-boundary-2-2": [1, "b11a05c301b00a8c6722daa5dafa64458706bae8097503f8da5e1884ba00f779"],
 "author-boundary-2-3": [1, "5225123205ac257e9bfb35830ea9acf1d50a46d1a199c5b8f5c66462ce5c689e"],
 "author-boundary-2-4": [1, "e40c3b3e7badd649c5a3c86ff7c526516a594782d37a1d791461241affa20591"],
 "author-boundary-3-0": [1, "55533227906e811cd757d6f9532c88e226e7f2841f1c3dd60b79177c57fb9b19"],
 "author-boundary-3-1": [1, "1525f959577d56585dc2f6d37dafec0fba948383c37360b31f6641dbec0694aa"],
 "author-boundary-3-2": [1, "b68dfca5b32850d5109f9b25aeb07c275f2f1292583cd2b3c5e894eb0d4caaf2"],
 "author-boundary-3-3": [1, "4b3fe175878210b72369c232beca497015dc8a86a4336887eda841c553f2dec2"],
 "author-boundary-3-4": [1, "f4bbc6793e4fe3f37bb92f8edfc7e520a539b260486aced032d8368f7a521197"],
 "author-boundary-4-0": [1, "3ecd3393b49b37ed5e6717c58df2213ff0e707089b38b0d0020fced045894d22"],
 "author-boundary-4-1": [1, "d47c802900d64fa434976b6616c8653574d70163cd3826b92f127c8be9532c4a"],
 "author-boundary-4-2": [1, "c988f8eb5e291ccbd516919a63d9b506d4e56564161661f638ae4cbd6544606b"],
 "author-boundary-4-3": [1, "154216cc28520f78d6ceda15a5627b139cb3d3ffbb7d8d2e1014532f7e87dc85"],
 "author-boundary-4-4": [1, "084374439f2bcb5a8bde5af4dbe2f7264d2dee41cb246617117355c5482e2f3c"],
 "author-boundary-5-0": [1, "500d14dc7e157cf5aedde8c4ef5571c263cc91141ce9bfe72deb0c2ea58f20df"],
 "author-boundary-5-1": [1, "1be9021ddb50e0e475a4112580330309ad452b3a96b1ba1600fe11915052377f"],
 "author-boundary-5-2": [1, "b94ee8f0b65a34a49141341fb0f1f5b31159be8b7c8b6a2c53c13e5ccc7d8f0f"],
 "author-boundary-5-3": [1, "1c46c16c688141c90a857181b59211af926aa2394e4c88655169e762b9c7096e"],
 "author-boundary-5-4": [1, "8b1a88b9bf42ef83a42fdb89a1127111b2167c5b3f181adc5592de664db95634"],
 "author-boundary-6-0": [1, "18e001ac7ac978c40eef8d4bad11c38a8bbb67016d9d93e85e339b4b4cfb66a6"],
 "author-boundary-6-1": [1, "e0b9f3b874b2176afb8639d129369bb184395347a9293ec5dea95ecd07f8b7e8"],
 "author-boundary-6-2": [1, "cb5885372fdef40a904914cc5ae0ac1149bf5deb96267447a3be69d7ce815388"],
 "author-boundary-6-3": [1, "412d6f19e38e888ae95ed0d92d6ca1ef656eb69ebbdd22bab926f6ad46fc8f14"],
 "author-boundary-6-4": [1, "3b6b5560aa7bf3e1fe5784394b829ab2d973e47610830b05e167cf2762d08e96"],
 "author-boundary-7-0": [1, "5a0ecae9e3ab50e8bfbda128f171fd9bb8820c474c32e115c82b6ff05c3f2026"],
 "author-boundary-7-1": [1, "31f5c05bca4a497e58c674ec5990967e81a26b7e7d99627d444a5d5c8fd86be0"],
 "author-boundary-7-2": [1, "de00e1b0663a3cb9dba5bf02bccc6dabe338c6533e13570bc65052bd30931752"],
 "author-boundary-7-3": [1, "373dce7dd1e4791ed959f15fd24512110538197f01de7db0d4d65d20d78c523a"],
 "author-boundary-7-4": [1, "1144aaa37b6ab121d70d02fdadfcf9c5d1a22b3ac872bb9850a8070e39f3b7ba"],
 "authors-11-0": [1, "9c74a27aaa718d5db1143575875d4056fa608b45250f01b7ba1f19bc27a10727"],
 "authors-11-1": [1, "1a6a71fe9c1e7e94f6c4fd1a9e7fe9506d30bc23f888064233b35bf4d7487e88"],
 "authors-11-2": [1, "20a17a9853eff99b141b9b993ca1888d5fd69197c3b01cccd638c0b2a6380ead"],
 "authors-11-3": [1, "900c6033699b1083dec08d15d2079645a3309d275fbaa3e460b3a84ac65c059c"],
 "authors-12-0": [1, "4c48b412e5d98b8991b38b90bcf49c284b701f7f36c360809bf28acbc9f49696"],
 "authors-12-1": [1, "492b44499e24bad8e3f10249200a180ba07b202a8caef602aef2571a43c1a439"],
 "authors-12-2": [1, "cd1bfd61d83acd213d5b206a1dd63cb3a3d8a906eece5cde0a6f6ac0f8651b3c"],
 "authors-12-3": [1, "fc3c69c5079198c021f376991ec5fe94d3f955ec6ce3ff0afb67e1b5a4f331e7"],
 "authors-250-0": [1, "89942c671b82d33846f289d4265dfb0560391726dad1d66db83849ba9f7d6067"],
 "authors-250-1": [1, "da36545858656d71613e908d405075e43ec54a970773505b7c88cfbd196c4bf8"],
 "authors-250-2": [1, "d41e4ddb0b7a1cc559a0132d6333004c3e6588d94367b525ed565a89fea47472"],
 "authors-250-3": [1, "6e9c5cc8fd9df22e1b97a0d0c32ce59a4e2698fe98fc2f069edf0d21bef6df6c"],
 "publication-0-0": [1, "32e0ab7d41d3a17a2530f418b133c06b0ba30ac36708f1d5191ce3ab33f7b15d"],
 "publication-0-1": [1, "f4a4ea8109ff75377e68c92329e16885c97d9206fa0206b1505d123ac91d91cb"],
 "publication-0-2": [1, "11a9564a19a599c20a7031720579cb8d839e246185acfa36f0c2ff089b04875e"],
 "publication-0-3": [1, "d42439338c5794f5b6476b27ebad73133959b1d8d5d3da86241ce8bb04428db4"],
 "publication-1-0": [1, "95dcc86f03183096a53c26514232717b0d42b126292dd6d7ab255c05032f1a93"],
 "publication-1-1": [1, "468eef164512b356aa25d228a2bfe8c81395327d0388bf3981396026c2ab9510"],
 "publication-1-2": [1, "80ee2bfd34242fbbc500b1b07bc30b2aefeffcfa66ebea8c3e34e2e3579ca797"],
 "publication-1-3": [1, "bd411d9b5a8d56b083c46d93acbcad31c769ba542ca433c5f0b3b724910bf816"],
 "publication-2-0": [1, "573d789dd2f1d9c4d3c081ee10de596b11a1e4256c48f623d8902ca7c86b1a10"],
 "publication-2-1": [1, "1b2ecfa04a4bf1e09b7e60eb9d3c8ea80ecce52ecfe7eaecf731f44c8b6fd9d1"],
 "publication-2-2": [1, "bd4b757661a06a328b2a87e842f868cb89ec6a93fa6454aefd2a99957caa523c"],
 "publication-2-3": [1, "3bcac89568d02c91c6b429dd82e79fb69be7c3129b2da3cc74d52d3d55ed3eca"],
 "publication-3-0": [1, "8ea87a42125d5645708f9cc3bbe22e7bd7deea90e8ed2c314be67731b34a01eb"],
 "publication-3-1": [1, "fd79a9b850e02cf1bad093439586f0f80c1039f5d73214c8c4793a4eb7cc1d05"],
 "publication-3-2": [1, "e93dd61807490f731338e746d1627397a8518a088740c4f1dba7820babb61503"],
 "publication-3-3": [1, "01b22955e9ed22aa146d4a4fbb99c3868adf580ed9fe79c486dbe5685555eae0"],
 "overlapping-title-0": [1, "60d60149efc3a9b42df0cdf8f238263981f13b823e101f9fcc810984bd96b03e"],
 "overlapping-title-1": [1, "ac849c3bcf495520fdaea48c5845f01f9596d7143b7c10c5d8a2a6e68d94b606"],
 "overlapping-title-2": [1, "d5060a285f9359eb247e7e8354ede9e1e41ceb2b949e2d94c303149bbce2daad"],
 "academic-control-0": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "academic-control-1": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "academic-control-2": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "academic-control-3": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "academic-control-4": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "academic-control-5": [1, "d82884b9d19b6bebc4cb09ca55931fae1b4c44bfd966ade760b3e80eadcde7e9"],
 "other-0": [1, "d807a669ea1666a7bbb695841332d9ba0f28e66b183244ff3102fed7710bd6c4"],
 "other-1": [1, "2d18c6cfcee601480422838827152c2e20b0e038ac94fafddb431126e30a21b4"],
 "other-2": [1, "1af453cc20b3d77239758ac26f830dc84acca706f3bede8876e9703096962cde"],
 "other-3": [1, "c44276cffbf33a85d18f3d3407bab77dfaa553c285350e45ba0b9964c9942a40"],
 "other-4": [1, "bca19135aeb677399f9608c56bf08712c51ff88005173e6e1a6633422ce60b3b"],
 "other-5": [1, "860f2c560aea9e4f43ea3984ac4251fefe7875c40f3fd547e1313598842bc69e"],
 "other-6": [1, "74d1230e11a2c62e3c57617af84399f4e5e9debe34e5eb07575e446656733a12"],
 "other-7": [1, "b0e58f177a0502578c43ce88a47572c6bec3778a325e314debb469f2be088d34"],
 "other-8": [1, "8103dfd3a2f9605d8456b592fc203d09044c91809e249039ebd0fe253986cd77"],
 "other-9": [1, "fb23a73e0590c5291203eff5b3a1bc13f04b87b9786ca0c57a23e9f22567aa50"],
 "other-10": [3, "84f11c5eea0c42f49b2e26f9e3962d9b280fe7bd1562ee101e6ebbb378131a2c"],
 "other-11": [3, "14b1d9d40a876969504bf1f58332236c759164a8431ea5865746ba2b05f40bae"],
 "other-12": [1, "9605ed3d3c1d1465062966db8eb4e6862e0ed05cf62b9ed9703fd3885b228098"],
 "other-13": [1, "9c9abbd2595bc5ef782cf96329363751d6b0965c240913c5bbae033f37030c7d"],
 "other-14": [2, "8ae594799a763c47a656335a07869189cdf7f88cee52e9ff893abda1623adbb6"],
 "other-15": [0, "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"],
 "other-16": [4, "1f34b98813924ea2a99cb43d659c639ef56732399cd14ca319e75bb914835bf1"],
 "long-case-0": [1, "c401d37efffa8294cafb78af97bb3a51fd563b61d87afb6c5da4b7ae2a6a01e2"],
 "long-case-1": [1, "220324b0a9d491362435d01ac854e9d4bd3aa7ab84c641b969cc18f4029eb2e7"],
 "long-case-2": [1, "89271c4c2c7a806665d826b25b02c1825d496c4789f0cd6f9acbcf225099dfdc"],
 "long-case-3": [1, "0e6caa9b88e5a21207976a2c7050844147f6cec3662f341df17b27b3f36b5ec6"],
 "long-case-4": [1, "1d35b798cc93832c4f1b64c951316e27654794171675a46f444f40d2601bd78c"],
 "long-case-5": [2, "ac90b56ef9ca0ca7b0c2134956809ce125adbb1069d881012696b9e0bad23dd2"],
 "long-statute-0": [1, "50821eb8450b30f82b6066091c557a9bf1187e9079d1f2411a08aef7fe8f5f71"],
 "long-statute-1": [1, "8ca0eb3ccb1e2f9aaee443e0d7175b5c10c5610dcb15bad28314508222311903"],
 "long-statute-2": [1, "6b5de198bdf0ec7759b699a0f8eebb27aa5634debbac2e6152dfd0e66bc06874"],
 "long-statute-3": [1, "a2cdda297e4934f49a94a03b3b391b8922f3f9f5a7a4940cfa05848e3176f515"],
 "long-statute-4": [1, "b42b0a504769a1953a54c411ef2f728b84c13dedd2ff6df1aa048d9fcdf0f422"],
 "long-lead": [1, "a408c81cfdc3c54727c43fda87e6a8fafdd46fac459e8194858662bf68c3665e"],
 "quote-repeat": [1, "aea3ba528d05600200914daf7318d484bbc38f252870b47ab3555a3f81834160"],
 "academic-repeat": [1, "3bd6081eea40fc54c53932f6a5d0cf25cf1fb4c8878ea5ccac759b0fe5831e21"],
 "mixed-repeat": [4, "98608cc126ca4fcf49b7f394f657153755a49148388fbe713649e30fe7a983c4"],
 "interpretation-number-only-0": [1, "4b3faa2fcd314d946975d7ae1b750151d4463734aac0fa8e40492e77186acd57"],
 "interpretation-number-only-1": [1, "38df1a26ff390c80b596d8bcfbf3d01db4306d4061e2f7491dc9bca27490b7ae"],
 "interpretation-number-only-2": [1, "c7c3d450d05002814a43af0a90a7c5f48cdd0bc650508cad87f4cd7f7efa2c78"],
 "alias-defined": [1, "ee98cf079f1228a28a85a18a8accaac67af5ff9b322c994686a2de1cbb18a7ef"],
 "alias-prefix-unique": [2, "02aa91c2e4a2c905eb7ebcfa348f53c511ea63c7c2f7774a1cdad4213b59c34c"],
 "alias-prefix-ambiguous": [3, "33cdbde3dcc5909f1faf9d85fecda934b9bda96584402011d54088faa5871193"],
 "alias-no-space": [2, "a0e5038b833121d40194692b9eacc2e1f7086696044aa19c3d7b2b2c215c85c6"],
 "alias-short": [2, "36ca3055c1b2f32dfd78239d1303c9e7ed3db2ce3eb9fac60c9ec436fd90b35f"],
 "alias-equal-clean": [2, "a68c8722d66f8d8672bb985a02ba6054257c984aa09fe9fb058397bb3b908a8b"]
}
''')


def _normalized(citations):
    ids = {c.citation_id: f"citation-{i}" for i, c in enumerate(citations)}
    data = [asdict(c) for c in citations]
    for row in data:
        row["citation_id"] = ids[row["citation_id"]]
        ref = row["attributes"].get("continued_from")
        if ref is not None:
            if ref not in ids:
                ids[ref] = f"external-{len(ids)}"
            row["attributes"]["continued_from"] = ids[ref]
    return json.loads(json.dumps(data, ensure_ascii=False))


def _doc(text):
    return NormalizedDocument("synthetic", "synthetic.txt", "text/plain", "synthetic",
                              pages=[Page(1, blocks=[Block("b1", text, 1)])])


@pytest.mark.parametrize("name", list(_samples()))
@pytest.mark.parametrize("actual_path", [False, True])
def test_full_baseline_output_contract(name, actual_path):
    text = _samples()[name]
    citations = extract_citations(_doc(text)) if actual_path else extract_from_text(text)
    snapshots = _DOCUMENT_OUTPUTS if actual_path else _TEXT_OUTPUTS
    expected_count, expected_digest = snapshots[name]
    data = _normalized(citations)
    digest = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    assert len(data) == expected_count
    assert digest == expected_digest, data


@pytest.mark.parametrize("court,year,number", [("헌재", "89", "101"), ("헌법재판소", "90", "102"), ("헌법 재판소", "91", "103")])
def test_approved_two_digit_constitutional_classification(court, year, number):
    citation = extract_citations(_doc(f"{court} 1994. 1. 2. {year}헌마{number}"))[0]
    assert citation.type == CitationType.CONSTITUTIONAL
    assert citation.case_kind == "결정"
    assert citation.canonical_case_number == f"{year}헌마{number}"


def test_unsealed_and_reordered_spans_keep_original_endpoint_contract():
    # 합성 순서·포함·경계를 원본의 두 끝점 조건과 비교한다.
    rng = random.Random(72)
    tracker, spans = SpanTracker(), []
    for i in range(160):
        start = rng.randrange(0, 900)
        end = start + rng.randrange(1, 200)
        tracker.add(start, end)
        spans.append((start, end))
        for _ in range(12):
            a = rng.randrange(0, 1100)
            b = a + rng.randrange(1, 300)
            expected = any(s <= a < e or s < b <= e for s, e in spans)
            assert tracker.overlaps(a, b) == expected
        if i % 23 == 0:
            tracker.seal_pattern()


@pytest.mark.parametrize("text", [
    '김가나, 「합성 학술 자료 제목」, 법문사, 2024',
    '김○○·이다라, 『합성 학술 자료 제목』, 법학논총 제2권, 2024',
    '"합성 직접 인용문의 문장"이라고 설명한다(김가나, 「합성 학술 자료 제목」, 법문사, 2024)',
])
def test_academic_public_match_groups_and_offsets(text):
    match = next(ACADEMIC_RE.finditer(text))
    assert match.group(0) == text[match.start():match.end()]
    assert match.group(1) == match.group("authors")
    assert match.group(2) == match.group("title")
    assert match.groupdict()["year"] == "2024"
    assert match.span("title") == (match.start("title"), match.end("title"))
    assert match.groups()[-1] == "2024"


@pytest.mark.parametrize("suffix", ["法령해석", "법령 해석", "유권판단"])
def test_interpretation_near_misses_are_not_extracted(suffix):
    assert not extract_citations(_doc(" " * 80_000 + suffix))


@pytest.mark.parametrize("suffix", ["법령해석", "유권해석", "법령해석례 24-0001"])
def test_interpretation_keyword_after_long_whitespace(suffix):
    started = time.perf_counter()
    citations = extract_citations(_doc(" " * 80_000 + suffix))
    elapsed = time.perf_counter() - started
    assert len(citations) == 1
    assert citations[0].type == CitationType.INTERPRETATION
    assert elapsed < 1.0


def test_new_index_and_matcher_short_repetitions():
    text = "김가나·이다라, 「합성 학술 자료 제목」, 법문사, 2024"
    body = text.index("「")
    started = time.perf_counter()
    for _ in range(2500):
        assert _author_start(text, body, 0) == 0
        assert next(_interpretation_matches("법제처 법령해석례 24-0001")).group("authority") == "법제처"
    assert time.perf_counter() - started < 0.1


def test_academic_repetition_actual_path_growth():
    line = "김가나, 「합성 학술 자료 제목」, 법문사, 2024.\n"
    times = []
    for count in (500, 2000, 8000):
        started = time.perf_counter()
        citations = extract_citations(_doc(line * count))
        times.append(time.perf_counter() - started)
        assert len(citations) == 1
        assert citations[0].authors == ["김가나"]
    assert times[-1] < 1.0
    assert times[-1] / max(times[-2], 1e-4) < 8.0


@pytest.mark.parametrize("separator", ["·", ",", ",\n"])
@pytest.mark.parametrize("count", [11, 12, 250])
def test_author_fields_keep_original_comma_and_dot_contract(separator, count):
    names = [f"저자{chr(0xAC00 + i)}" for i in range(count)]
    text = separator.join(names) + ", 「합성 학술 자료 제목」, 법문사, 2024"
    citation = extract_citations(_doc(text))[0]
    expected = names if separator == "·" else [separator.join(names)]
    assert citation.authors == expected
    assert citation.raw_text == text
    assert citation.span == (0, len(text))


def test_batch_ids_are_finalized_for_body_table_and_continued_references():
    import re
    text = "「민법」 제750조 및 제751조.\n" * 4
    doc = _doc(text)
    doc.pages[0].blocks.append(Block("table", "", 1, block_type="table",
                                   attributes={"cells": [[text], [text]]}))
    citations = extract_citations(doc)
    assert any("table_cell" in c.attributes for c in citations)
    assert any("continued_from" in c.attributes for c in citations)
    assert len({c.citation_id for c in citations}) == len(citations)
    for citation in citations:
        assert re.fullmatch(r"CIT_[0-9a-f]{12}", citation.citation_id)
        ref = citation.attributes.get("continued_from")
        if ref is not None:
            assert re.fullmatch(r"CIT_[0-9a-f]{12}", ref)


def test_academic_negative_public_searches_with_long_whitespace_are_bounded():
    text = '김가나, 「합성 학술 자료 제목」, 법학논총' + " " * 80_000 + "x"
    started = time.perf_counter()
    assert not list(ACADEMIC_RE.finditer(text))
    assert not extract_citations(_doc(text))
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize("text", [
    "본문\n계속", "본문\n\n계속", "본문\n  계속",
    "본문\n 1. 항목", "본문.\n계속", "본문\n- 항목",
    "본문\n\n  가) 항목", "본문\n\t\r 12) 항목", "본문;\n계속",
])
def test_claim_line_join_keeps_original_positive_and_negative_contract(text):
    import re
    from packages.legal_engine.citation_extractor import _unwrap_claim_lines
    original = re.sub(r"(?<![.\?!:;])\n(?!\s*(?:\d+[\.)]|[가-하][\.)]|[-•*]))", " ", text)
    assert _unwrap_claim_lines(text) == original


@pytest.mark.parametrize("tail", ["\n" * 80_000 + "x", "\n " * 40_000 + "x",
                                  "\n" * 80_000 + "1" * 20_000 + "x"])
def test_claim_line_join_long_whitespace_actual_path(tail):
    started = time.perf_counter()
    citations = extract_citations(_doc("「민법」 제750조" + tail))
    elapsed = time.perf_counter() - started
    assert len(citations) == 1
    assert citations[0].attributes["claim_text"] == tail.strip()[:400]
    assert elapsed < 1.0


def test_claim_line_join_short_repetitions():
    from packages.legal_engine.citation_extractor import _unwrap_claim_lines
    started = time.perf_counter()
    for _ in range(2500):
        assert _unwrap_claim_lines("본문\n\n 1. 항목\n계속") == "본문\n\n 1. 항목 계속"
    assert time.perf_counter() - started < 0.1
