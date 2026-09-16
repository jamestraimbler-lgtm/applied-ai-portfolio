// CSS module imports return a map of class names.
declare module "*.module.css" {
  const classes: { readonly [key: string]: string };
  export default classes;
}
