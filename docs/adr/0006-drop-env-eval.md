# EnvEval is out of scope

EnvEval was a Python module (about 10k source lines and 11k test lines) that scored how usable a storefront is as an RL environment, using BrowserGym observations and actions. We deleted it in the TypeScript rewrite instead of porting it, because nothing else depended on it and it was built on the BrowserGym stack we removed. ShopGym now has no environment-quality metric and no structural-variance comparison between generated shops; the build verifiers and `final_eval` check one shop at a time.
