import React, {useEffect, useState} from 'react';
import {Modal, Pressable, ScrollView, Switch, Text, TextInput, View} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import type {Favorite} from '../domain/favorites';
import {styles as s} from '../theme';
import {Button} from './Button';
export function FavoriteEditor({favorite, busy, onSave, onClose}: {
  favorite: Favorite | null; busy: boolean; onSave: (value: Favorite) => void; onClose: () => void;
}) {
  const [draft, setDraft] = useState<Favorite | null>(favorite);
  useEffect(() => {setDraft(favorite);}, [favorite]);
  return <Modal visible={favorite !== null} animationType="slide" onRequestClose={onClose}>
    <SafeAreaView style={s.screen}><ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={s.content}>
      <Text style={s.title}>즐겨찾기 설정</Text>
      {draft && <>
        <Text style={s.text}>{draft.origin.name} → {draft.destination.name}</Text>
        <Text style={s.small}>이름</Text><TextInput accessibilityLabel="즐겨찾기 이름" style={s.input} value={draft.label} maxLength={40} onChangeText={label => setDraft({...draft, label})} />
        <View style={s.row}><Text style={[s.text, {flex: 1}]}>출퇴근 자동 시작</Text><Switch accessibilityLabel="출퇴근 자동 시작" value={draft.enabled} onValueChange={enabled => setDraft({...draft, enabled})} /></View>
        <View style={s.notice}><Text style={s.small}>설정한 시간에 출발역 300m 이내 접근을 감지하면 탑승 확인을 준비합니다. 실제 탑승 열차는 직접 확인해야 합니다. Android가 감지를 지연할 수 있습니다.</Text></View>
        <Text style={s.small}>요일 (한국 시간)</Text>
        <View style={s.row}>{['월','화','수','목','금','토','일'].map((name, i) => <Pressable accessibilityRole="checkbox" accessibilityState={{checked: draft.days.includes(i + 1)}} key={name}
          style={[s.chip, draft.days.includes(i + 1) && s.chipSelected]}
          onPress={() => setDraft({...draft, days: draft.days.includes(i + 1) ? draft.days.filter(d => d !== i + 1) : [...draft.days, i + 1].sort()})}>
          <Text style={s.text}>{name}</Text></Pressable>)}</View>
        <Text style={s.small}>시간대 · HH:mm (예: 07:00 / 10:00)</Text>
        <View style={s.row}><TextInput accessibilityLabel="시작 시간" style={[s.input, {flex: 1}]} value={draft.start} maxLength={5} onChangeText={start => setDraft({...draft, start})} />
          <Text style={s.text}>~</Text><TextInput accessibilityLabel="종료 시간" style={[s.input, {flex: 1}]} value={draft.end} maxLength={5} onChangeText={end => setDraft({...draft, end})} /></View>
        <Text style={s.small}>23:00~02:00처럼 자정을 넘으면 시작한 날짜의 요일을 적용합니다. 같은 규칙은 하루 한 번만 자동 시작합니다.</Text>
        <Button label={busy ? '저장 중…' : '저장'} disabled={busy} onPress={() => onSave(draft)} />
      </>}
      <Button label="취소" secondary disabled={busy} onPress={onClose} />
    </ScrollView></SafeAreaView>
  </Modal>;
}
