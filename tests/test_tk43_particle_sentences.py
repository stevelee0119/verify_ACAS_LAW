"""Synthetic TK-43 sentences: noun readability and names at the provider boundary.

All text, names, and test-only category entries are synthetic. No user brief or
private/protected test vocabulary is used to define a product rule or dictionary.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from time import perf_counter
from types import SimpleNamespace

import pytest

from packages.common.enums import LLMRole
from packages.llm_router import privacy, router as router_module
from packages.llm_router.providers import LLMRequest, LLMResponse
from packages.pii_engine import PIIEngine, PseudonymStore, detect
from packages.pii_engine import detector

# Three distinct examples per distinguishable grammatical shape.
NOUN_SENTENCES = [
    ('multi-particle', '소득으로', '자료를 정리하였다.'),
    ('multi-particle', '신분에서', '절차에 참가하였다.'),
    ('multi-particle', '경력에게', '평가 항목을 배정하였다.'),
    ('long-word', '명세서와', '별첨 문서를 대조하였다.'),
    ('long-word', '동의서는', '다음 쪽에 첨부하였다.'),
    ('long-word', '차용증을', '별도 자료로 제출하였다.'),
    ('no-surname', '자료는', '뒤에 첨부하였다.'),
    ('no-surname', '재산은', '별도로 검토하였다.'),
    ('no-surname', '업무가', '여러 부서에 분산되었다.'),
]
LABELS = ['원고', '증인', '작성자', '담당자', '진술인', '매수인', '임차인', '보호자', '후견인']
# Same-prefix names and names whose last syllable resembles a particle.
NAME_SENTENCES = [
    ('소득윤', '에게', '자료를 전달하였다.'),
    ('신분솔', '으로', '대상을 지정하였다.'),
    ('경력린', '은', '첨부 문서를 확인하였다.'),
    ('소득은', '', '관련 자료와 무관하다.'),
    ('신원이', '', '별도 자료를 확인하였다.'),
    ('경력도', '', '확인 내용과 무관하다.'),
    ('소득은', '에게', '자료를 전달하였다.'),
    ('신원이', '에서', '확인 절차를 시작하였다.'),
    ('경력도', '은', '첨부 문서를 확인하였다.'),
    ('소득이', '라고', '자료에 기재하였다.'),
    ('신원이', '라고', '별첨 문서에 기재하였다.'),
    ('경력이', '라고', '확인 자료에 기재하였다.'),
]


@pytest.fixture
def engine(tmp_path):
    return PIIEngine(PseudonymStore('synthetic-tk43-sentence', root=tmp_path))


@pytest.mark.parametrize('shape,word,tail', NOUN_SENTENCES)
@pytest.mark.parametrize('label', LABELS)
@pytest.mark.parametrize('delimiter', [' ', ': ', '：'])
def test_distinguishable_noun_sentence_is_not_masked(engine, shape, word, tail, label, delimiter):
    text = f'{label}{delimiter}{word} {tail}'
    assert not [m for m in detect(text) if m.kind == 'PERSON']
    assert engine.mask_text(text).masked_text == text
    assert privacy.inspect_request(LLMRequest(system='합성 자료 검토', user=text))['status'] == 'PASSED'


@pytest.mark.parametrize('name,particle,tail', NAME_SENTENCES)
@pytest.mark.parametrize('label', LABELS)
@pytest.mark.parametrize('spacing', ['plain', 'all', 'partial'])
def test_sentence_name_and_ambiguous_noun_reading_stay_private(engine, name, particle, tail, label, spacing):
    rendered = name if spacing == 'plain' else (' '.join(name) if spacing == 'all' else name[:2] + ' ' + name[2:])
    text = f'{label} {rendered}{particle} {tail}'
    people = [m for m in detect(text) if m.kind == 'PERSON']
    assert people and ''.join(rendered.split()) in ''.join(m.text for m in people)
    masked = engine.mask_text(text).masked_text
    assert rendered not in masked and '[PERSON_' in masked
    assert privacy.inspect_request(LLMRequest(system=text, user='合成'))['status'] == 'BLOCKED'
    assert privacy.inspect_request(LLMRequest(system=masked, user='合成'))['status'] == 'PASSED'


@pytest.mark.parametrize('word', ['명세서와', '동의서는', '차용증을'])
def test_direct_name_label_does_not_get_sentence_stopword_exclusion(engine, word):
    # Synthetic four-syllable names: the explicit name signal remains private.
    text = f'성명: {word} 관련 자료를 확인하였다.'
    assert not detector._is_category_person_sentence_stopword(text, 4, explicit_name=True)
    assert '[PERSON_' in engine.mask_text(text).masked_text


@pytest.mark.parametrize('surname,ending', [('남궁', '은'), ('황보', '이'), ('선우', '도')])
def test_double_surname_ambiguity_uses_structure_not_dictionary_entries(monkeypatch, engine, surname, ending):
    # Test-only nominal identifiers create the otherwise absent overlap branch.
    synthetic_noun = surname + '표'
    monkeypatch.setattr(detector, 'PERSON_CATEGORY_STOPWORDS',
                        detector.PERSON_CATEGORY_STOPWORDS | {synthetic_noun})
    word = synthetic_noun + ending
    text = f'작성자 {word} 관련 자료와 무관하다.'
    assert not detector._is_category_person_sentence_stopword(text, 4)
    assert '[PERSON_' in engine.mask_text(text).masked_text


@pytest.mark.parametrize('word', ['소득은은', '신원이는', '경력도도'])
def test_particles_are_not_recursively_removed(engine, word):
    text = f'작성자 {word} 관련 자료를 확인하였다.'
    assert not detector._is_category_person_sentence_stopword(text, 4)
    assert '[PERSON_' in engine.mask_text(text).masked_text


@pytest.fixture
def cloud_boundary(monkeypatch):
    """Actual router with a synthetic cloud-provider double and ledger."""
    sent = []
    monkeypatch.setattr(router_module, 'estimate_call', lambda *args: (Decimal('0.01'), {}))

    class Provider:
        name, available = 'anthropic', True
        config = SimpleNamespace(name='anthropic', kind='cloud', model='fake', enabled=True)

        async def generate(self, request):
            sent.append(request)
            return LLMResponse(True, text='확인', provider=self.name, model=self.config.model)

    ledger = SimpleNamespace(
        reserve=lambda *args, **kwargs: SimpleNamespace(id='r', amount=Decimal('0.01')),
        dispatch=lambda *args, **kwargs: None,
        settle=lambda *args, **kwargs: None,
    )
    router = router_module.LLMRouter(providers={'anthropic': Provider()}, ledger=ledger)

    def run(text, position):
        request = LLMRequest(system=text if position == 'system' else '합성 자료 검토',
                             user=text if position == 'user' else '합성 자료 검토')
        asyncio.run(router.run(LLMRole.PRIMARY_REASONER, request))

    return sent, run


@pytest.mark.parametrize('position', ['system', 'user'])
@pytest.mark.parametrize('label', ['작성자', '진술인', '임차인', '후견인'])
@pytest.mark.parametrize('shape,word,tail', NOUN_SENTENCES)
def test_real_router_sends_distinguishable_noun_sentences(cloud_boundary, position, label, shape, word, tail):
    sent, run = cloud_boundary
    text = f'{label} {word} {tail}'
    run(text, position)
    assert len(sent) == 1 and getattr(sent[0], position).endswith(text)


@pytest.mark.parametrize('position', ['system', 'user'])
@pytest.mark.parametrize('label', ['작성자', '진술인', '임차인', '후견인'])
@pytest.mark.parametrize('name,particle,tail', NAME_SENTENCES)
@pytest.mark.parametrize('spacing', ['plain', 'partial'])
def test_real_router_blocks_sentence_names_and_sends_only_masked_text(engine, cloud_boundary, position, label, name, particle, tail, spacing):
    sent, run = cloud_boundary
    rendered = name if spacing == 'plain' else name[:2] + ' ' + name[2:]
    text = f'{label} {rendered}{particle} {tail}'
    run(text, position)
    assert not sent
    run(engine.mask_text(text).masked_text, position)
    assert len(sent) == 1 and rendered not in sent[0].system + sent[0].user


def test_original_word_path_repeated_sentence_input_time():
    """Synthetic 6,000 sentence-shaped calls, including both privacy directions."""
    cases = [
        ('작성자 소득으로 자료를 정리하였다.', 4, True),
        ('임차인 명세서와 별첨 문서를 대조하였다.', 4, True),
        ('보호자 자료는 뒤에 첨부하였다.', 4, True),
        ('작성자 소득은 관련 자료와 무관하다.', 4, False),
        ('임차인 신원이 관련 자료와 무관하다.', 4, False),
        ('보호자 경력도 관련 자료와 무관하다.', 4, False),
        ('작성자 신원이라고 자료에 기재하였다.', 4, False),
        ('임차인 소득이라고 별첨 문서에 기재하였다.', 4, False),
    ] * 750
    started = perf_counter()
    results = [detector._is_category_person_sentence_stopword(text, start) for text, start, _ in cases]
    elapsed = perf_counter() - started
    assert results == [expected for _, _, expected in cases]
    print(f'TK-43 sentence word path 6,000 calls: {elapsed:.6f}s')
    assert elapsed < 0.1


def test_label_regex_repeated_sentence_input_time():
    """Synthetic 2,000 sentences exercise the changed bounded particle regex."""
    lines = ['작성자 소득윤에게 자료를 전달하였다.', '임차인 신원이에게 별첨 문서를 전달하였다.'] * 1000
    text = '\n'.join(lines)
    started = perf_counter()
    matches = list(detector._LABELLED_COMPOUND_PERSON_RE.finditer(text))
    elapsed = perf_counter() - started
    assert len(matches) == 2000
    assert [m.group(1) for m in matches[:2]] == ['소득윤', '신원이']
    print(f'TK-43 label regex 2,000 sentences: {elapsed:.6f}s')
    assert elapsed < 0.1
