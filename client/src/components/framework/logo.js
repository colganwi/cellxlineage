import React from "react";
import logo from "../../images/logo.png";

const Logo = ({ height = 32 }) => (
  <img
    src={logo}
    height={height}
    style={{ width: "auto" }}
    alt="cellxlineage logo"
  />
);

export default Logo;
