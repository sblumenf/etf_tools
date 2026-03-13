declare module "react-simple-maps" {
  import { ComponentType, ReactNode, SVGProps } from "react";

  interface ComposableMapProps {
    projectionConfig?: Record<string, unknown>;
    style?: React.CSSProperties;
    children?: ReactNode;
  }

  interface ZoomableGroupProps {
    children?: ReactNode;
    [key: string]: unknown;
  }

  interface GeographiesProps {
    geography: string;
    children: (args: { geographies: GeographyFeature[] }) => ReactNode;
  }

  interface GeographyFeature {
    rsmKey: string;
    id: string | number;
    type: string;
    properties: Record<string, unknown>;
  }

  interface GeographyProps extends SVGProps<SVGPathElement> {
    geography: GeographyFeature;
    style?: {
      default?: React.CSSProperties;
      hover?: React.CSSProperties;
      pressed?: React.CSSProperties;
    };
  }

  export const ComposableMap: ComponentType<ComposableMapProps>;
  export const ZoomableGroup: ComponentType<ZoomableGroupProps>;
  export const Geographies: ComponentType<GeographiesProps>;
  export const Geography: ComponentType<GeographyProps>;
}
