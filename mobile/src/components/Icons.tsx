import React from "react";
import Svg, { Path, Circle, Rect, Polygon } from "react-native-svg";

type P = { size?: number; color?: string; strokeWidth?: number };

const S = ({ size = 24, children }: { size?: number; children: React.ReactNode }) => (
  <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
    {children}
  </Svg>
);

export const Check = ({ size = 16, color = "#fff", strokeWidth = 3 }: P) => (
  <S size={size}>
    <Path d="M5 12l4 4 10-10" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
  </S>
);

export const CheckCircle = ({ size = 18, color = "#00c2a8", ink = "#04201c" }: P & { ink?: string }) => (
  <S size={size}>
    <Circle cx="12" cy="12" r="9" fill={color} />
    <Path d="M8 12l3 3 5-6" stroke={ink} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round" />
  </S>
);

export const Play = ({ size = 20, color = "#04201c" }: P) => (
  <S size={size}>
    <Polygon points="8,5 19,12 8,19" fill={color} />
  </S>
);

export const Home = ({ size = 24, color = "currentColor", strokeWidth = 1.9 }: P) => (
  <S size={size}>
    <Path d="M4 11 12 4l8 7" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    <Path d="M6 11v8h12v-8" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
  </S>
);

export const Plus = ({ size = 24, color = "currentColor", strokeWidth = 1.9 }: P) => (
  <S size={size}>
    <Circle cx="12" cy="12" r="9" stroke={color} strokeWidth={strokeWidth} />
    <Path d="M12 8v8M8 12h8" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
  </S>
);

export const Grid = ({ size = 24, color = "currentColor", strokeWidth = 1.9 }: P) => (
  <S size={size}>
    <Rect x="4" y="4" width="7" height="7" rx="1.6" stroke={color} strokeWidth={strokeWidth} />
    <Rect x="13" y="4" width="7" height="7" rx="1.6" stroke={color} strokeWidth={strokeWidth} />
    <Rect x="4" y="13" width="7" height="7" rx="1.6" stroke={color} strokeWidth={strokeWidth} />
    <Rect x="13" y="13" width="7" height="7" rx="1.6" stroke={color} strokeWidth={strokeWidth} />
  </S>
);

export const User = ({ size = 24, color = "currentColor", strokeWidth = 1.9 }: P) => (
  <S size={size}>
    <Circle cx="12" cy="9" r="3.4" stroke={color} strokeWidth={strokeWidth} />
    <Path d="M5.5 19.5c0-3.6 3-5.5 6.5-5.5s6.5 1.9 6.5 5.5" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
  </S>
);

export const Download = ({ size = 17, color = "#04201c", strokeWidth = 2.2 }: P) => (
  <S size={size}>
    <Path d="M12 4v11m0 0 4-4m-4 4-4-4" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    <Path d="M5 19h14" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
  </S>
);

export const Share = ({ size = 19, color = "#fff", strokeWidth = 2 }: P) => (
  <S size={size}>
    <Path d="M12 15V4m0 0 4 4m-4-4-4 4" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
    <Path d="M5 13v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
  </S>
);

export const Refresh = ({ size = 15, color = "currentColor", strokeWidth = 2 }: P) => (
  <S size={size}>
    <Path d="M4 12a8 8 0 1 1 2.5 5.8" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
    <Path d="M4 12v-4M4 12h4" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
  </S>
);

export const Copy = ({ size = 14, color = "#fff", strokeWidth = 1.9 }: P) => (
  <S size={size}>
    <Rect x="8" y="8" width="12" height="12" rx="2.5" stroke={color} strokeWidth={strokeWidth} />
    <Path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" stroke={color} strokeWidth={strokeWidth} />
  </S>
);

export const Camera = ({ size = 18, color = "#04201c", strokeWidth = 1.9 }: P) => (
  <S size={size}>
    <Path d="M9 4h6l1.5 2.5H20a1 1 0 0 1 1 1V19a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7.5a1 1 0 0 1 1-1h3.5L9 4Z" stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round" />
    <Circle cx="12" cy="13" r="3.4" stroke={color} strokeWidth={strokeWidth} />
  </S>
);

export const Bell = ({ size = 18, color = "#00c2a8", strokeWidth = 1.8 }: P) => (
  <S size={size}>
    <Path d="M6 8a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6Z" stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round" />
    <Path d="M10 19a2 2 0 0 0 4 0" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" />
  </S>
);

export const ChevronBack = ({ size = 18, color = "#f4f4f5", strokeWidth = 2 }: P) => (
  <S size={size}>
    <Path d="M15 5l-7 7 7 7" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />
  </S>
);

export const Apple = ({ size = 17, color = "#fff" }: P) => (
  <S size={size}>
    <Path
      d="M16.5 3c.1 1.2-.4 2.4-1.1 3.2-.8.9-2 1.6-3.2 1.5-.1-1.2.5-2.4 1.2-3.1.8-.9 2.1-1.5 3.1-1.6ZM19 17c-.5 1.2-.8 1.7-1.5 2.7-1 1.5-2.4 3.3-4.1 3.3-1.5 0-1.9-1-4-1-2 0-2.5 1-4 1-1.7 0-3-1.7-4-3.1C-.4 16.6-.9 11 1.6 8c1.2-1.5 2.9-2.4 4.6-2.4 1.7 0 2.8 1 4.2 1 1.4 0 2.2-1 4.2-1 1.5 0 3.1.8 4.2 2.2-3.7 2-3.1 7.3.2 9.2Z"
      fill={color}
    />
  </S>
);
