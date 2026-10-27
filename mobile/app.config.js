// Firebase Android config is optional and only read while generating a native build.
module.exports=({config})=>{
  const googleServicesFile=process.env.GOOGLE_SERVICES_JSON;
  return {...config,android:{...config.android,...(googleServicesFile?{googleServicesFile}:{})}};
};
