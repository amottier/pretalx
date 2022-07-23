import Vue from 'vue'
import App from './App.vue'
import '~/styles/global.styl'

Vue.config.productionTip = false

new Vue({
	render: h => h(App, {
		props: {
			locale: 'en-ie'
		}
	})
}).$mount('#app')
