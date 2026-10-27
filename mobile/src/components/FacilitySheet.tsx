import React from 'react';
import {Linking, Modal, ScrollView, Text, View} from 'react-native';
import {SafeAreaView} from 'react-native-safe-area-context';
import type {StationDetail, Facility} from '../types';
import {styles as s} from '../theme';
import {Button} from './Button';
const categories: {kind: Facility['kind']; label: string}[] = [
  {kind: 'TRANSFER', label: '빠른 환승'}, {kind: 'TOILET', label: '화장실'}, {kind: 'AMENITY', label: '편의시설'},
  {kind: 'GATE', label: '개찰구'}, {kind: 'EXIT', label: '출구'},
];
export function FacilitySheet({detail, onClose}: {detail: StationDetail | null; onClose: () => void}) {
  return <Modal visible={detail !== null} animationType="slide" onRequestClose={onClose}>
    <SafeAreaView style={s.screen}>
      <ScrollView contentContainerStyle={s.content}>
        <Text style={s.title}>{detail?.station.name}</Text>
        <Text style={s.small}>{detail?.informationNotice}</Text>
        {detail?.station.source === 'SYNTHETIC_DEMO' && <View style={s.notice}><Text style={s.text}>가상 역입니다. 실제 시설 위치를 제공하지 않습니다.</Text></View>}
        {categories.map(({kind, label}) => {
          const items = detail?.facilities.filter(f => f.kind === kind) ?? [];
          return <View style={s.card} key={kind}>
            <Text style={s.heading}>{label}</Text>
            {items.length === 0 ? <Text style={s.small}>검증된 정보가 아직 등록되지 않았습니다.</Text> : items.map((f, i) => <View key={`${f.title}-${i}`} style={{gap: 5}}>
              <Text style={s.text}>{f.title}</Text><Text style={s.text}>{f.location}</Text>
              {f.carDoor && <Text style={s.text}>승차 위치: {f.carDoor}</Text>}
              {f.transferLine && <Text style={s.small}>환승 호선: {f.transferLine}</Text>}
              {f.direction && <Text style={s.small}>방향: {f.direction}</Text>}
              {f.gateSide && <Text style={s.small}>개찰구 기준: {f.gateSide}</Text>}
              <Text style={s.small}>확인일: {f.verifiedAt.slice(0, 10)}</Text>
              {/^https:\/\//.test(f.sourceUrl) && <Button label="정보 출처 보기" secondary onPress={() => {void Linking.openURL(f.sourceUrl).catch(() => {});}} />}
            </View>)}
          </View>;
        })}
        <Button label="닫기" onPress={onClose} />
      </ScrollView>
    </SafeAreaView>
  </Modal>;
}
