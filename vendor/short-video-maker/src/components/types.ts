export enum AvailableComponentsEnum {
  PortraitVideo = "ShortVideo",
  LandscapeVideo = "LandscapeVideo",
}
export type OrientationConfig = {
  width: number;
  height: number;
  component: AvailableComponentsEnum;
};
