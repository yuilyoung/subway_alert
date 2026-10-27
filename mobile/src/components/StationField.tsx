import React, {useEffect, useRef, useState} from 'react';
import {Pressable, Text, TextInput, View} from 'react-native';
import type {Api} from '../api';
import type {Station} from '../domain/favorites';
import {normalizeQuery} from '../domain/favorites';
import {styles as s} from '../theme';

export function StationField({label, api, selected, lineId, onSelect, onClear}: {
  label: string; api: Api; selected: Station | null; lineId?: string;
  onSelect: (station: Station) => void; onClear: () => void;
}) {
  const [query, setQuery] = useState(selected?.name ?? '');
  const [editing, setEditing] = useState(false);
  const [results, setResults] = useState<Station[]>([]);
  const [message, setMessage] = useState('');
  const sequence = useRef(0);
  useEffect(() => { if (selected) {setQuery(selected.name); setEditing(false);} }, [selected]);
  useEffect(() => {
    if (!editing) return;
    const request = ++sequence.current;
    const timer = setTimeout(() => {
      setMessage('검색 중…');
      api.search(normalizeQuery(query), lineId).then(items => {
        if (request !== sequence.current) return;
        setResults(items.slice(0, 8)); setMessage(items.length ? '' : '등록된 역이 없습니다. 역명이나 호선을 확인하세요.');
      }).catch((error: Error) => {if (request === sequence.current) {setResults([]); setMessage(error.message);}});
    }, 250);
    return () => {clearTimeout(timer); sequence.current++;};
  }, [api, query, lineId, editing]);
  return <View style={{gap: 8}}>
    <Text style={s.small}>{label}</Text>
    <TextInput accessibilityLabel={`${label} 검색`} style={s.input} value={query} placeholder="역 이름을 입력하세요" autoCorrect={false}
      onFocus={() => setEditing(true)} onChangeText={text => {setQuery(text); setEditing(true); onClear();}} />
    {editing && <View>
      {message !== '' && <Text style={s.small}>{message}</Text>}
      {results.map(station => <Pressable accessibilityRole="button" key={station.id} style={s.result}
        onPress={() => {setEditing(false); setQuery(station.name); onSelect(station);}}>
        <Text style={s.text}>{station.name}</Text><Text style={s.small}>{station.lineId} · 검색 결과에서 선택</Text>
      </Pressable>)}
    </View>}
  </View>;
}
