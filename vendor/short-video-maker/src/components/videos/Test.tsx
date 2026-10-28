import { AbsoluteFill, Sequence } from "remotion";

export const TestVideo: React.FC = () => {
  return (
    <AbsoluteFill>
      <AbsoluteFill>
        <AbsoluteFill>
          <h1>Hello</h1>
        </AbsoluteFill>
        <Sequence from={10}>
          <h1 style={{ marginTop: "60px" }}>World</h1>
        </Sequence>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
