import React from "react";
import { View, Image, useWindowDimensions } from "react-native";
import { Asset } from "expo-asset";
import { LinearGradient } from "expo-linear-gradient";
import { StylePreview } from "./StylePreview";

export function SignInShowcase() {
  const { width } = useWindowDimensions();
  const cardWidth = Math.min(width * 0.43, 185);
  return <View pointerEvents="none" style={{ position: "absolute", top: 0, bottom: 0, left: 0, right: 0, overflow: "hidden", backgroundColor: "#0e0e11" }}>
    <View style={{ position: "absolute", top: 65, left: "50%", width: 0 }}>
      {[
        { photo: require("../../public/previews/bakery_morning.poster.jpg"), left: -cardWidth * 1.25, top: 25, rotate: "-16deg" },
        { photo: require("../../public/previews/skincare_glow.poster.jpg"), left: -cardWidth * 0.5, top: -30, rotate: "-4deg", video: true },
        { photo: require("../../public/previews/jewelry_detail.poster.jpg"), left: cardWidth * 0.3, top: 55, rotate: "14deg" },
      ].map((card, i) => <View key={i} style={{ position: "absolute", left: card.left, top: card.top, width: cardWidth, height: cardWidth * 16 / 9, transform: [{ rotate: card.rotate }], borderRadius: 20, backgroundColor: "#153c36", shadowColor: "#000", shadowOpacity: 0.65, shadowRadius: 24, shadowOffset: { width: 0, height: 16 }, elevation: 8 }}>
        {card.video ? <StylePreview uri={Asset.fromModule(require("../../public/previews/skincare_glow.preview.mp4")).uri} poster={Asset.fromModule(card.photo).uri} mode="video" aspectRatio={9 / 16} />
          : <Image source={card.photo} resizeMode="cover" style={{ width: "100%", height: "100%", borderRadius: 20 }} />}
      </View>)}
    </View>
    <LinearGradient colors={["rgba(14,14,17,0.25)", "rgba(14,14,17,0.72)", "#0e0e11", "#0e0e11"]} locations={[0, 0.3, 0.65, 1]} style={{ position: "absolute", top: 0, bottom: 0, left: 0, right: 0 }} />
  </View>;
}
